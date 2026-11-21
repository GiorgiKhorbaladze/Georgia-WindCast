"""Model adapters for the challenger tournament (Issue #57). Same interface for every model.

``fit_predict(train, test, features, horizon, hourly_series) -> predictions for test rows``.
Hyper-parameters are fixed and documented here (no tuning on test folds). Optional libraries are
imported only inside each adapter.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

import numpy as np
import pandas as pd

SEED = 57


@dataclass
class ModelSpec:
    model_id: str
    library: str | None  # import name, None = numpy only

    def status(self) -> str:
        return "available" if self.library is None or importlib.util.find_spec(self.library) else "unavailable"

    def fit_predict(self, train: pd.DataFrame, test: pd.DataFrame, feats: list[str], horizon: int,
                    y: pd.Series) -> np.ndarray:
        raise NotImplementedError


def _xy(df: pd.DataFrame, feats: list[str]) -> np.ndarray:
    return df[feats].to_numpy(dtype=float)


def _clip(p: np.ndarray, train: pd.DataFrame) -> np.ndarray:
    return np.clip(p, 0.0, float(train["y"].max()) * 1.1)


class Persistence(ModelSpec):
    def __init__(self):
        super().__init__("persistence", None)

    def fit_predict(self, train, test, feats, horizon, y):
        return test["lag1"].to_numpy(dtype=float)


class RidgeLags(ModelSpec):
    """Ridge on standardised lags/hour features (numpy); missing features imputed with train means."""

    def __init__(self, alpha: float = 1.0):
        super().__init__("ridge", None)
        self.alpha = alpha

    def fit_predict(self, train, test, feats, horizon, y):
        mu = train[feats].mean()
        Xtr, Xte = _xy(train[feats].fillna(mu), feats), _xy(test[feats].fillna(mu), feats)
        m, s = Xtr.mean(0), Xtr.std(0)
        s[s == 0] = 1
        Z, Zt = (Xtr - m) / s, (Xte - m) / s
        yt = train["y"].to_numpy()
        coef = np.linalg.solve(Z.T @ Z + self.alpha * np.eye(Z.shape[1]), Z.T @ (yt - yt.mean()))
        return _clip(Zt @ coef + yt.mean(), train)


class Sarima(ModelSpec):
    """SARIMA(1,0,1)x(1,0,0,24) on the hourly series up to each issue (statsmodels, state-space).

    Fitted once per fold on the training history, then filtered forward with the parameters held
    fixed up to each issue time (no refit on test data). Exogenous weather turns it into SARIMAX
    once as-of weather runs exist for every training hour (not before)."""

    def __init__(self):
        super().__init__("sarima", "statsmodels")

    def fit_predict(self, train, test, feats, horizon, y):
        import warnings

        from statsmodels.tsa.statespace.sarimax import SARIMAX

        warnings.filterwarnings("ignore", module="statsmodels")  # frequency/convergence notices
        cutoff = train["target_start"].max() + pd.Timedelta(hours=1)
        hist = y[y.index < cutoff].iloc[-24 * 21:]
        model = SARIMAX(hist, order=(1, 0, 1), seasonal_order=(1, 0, 0, 24), trend="c",
                        enforce_stationarity=False, enforce_invertibility=False, missing="drop")
        res = model.fit(disp=False, maxiter=50)
        out = []
        for issue in test.index:
            upto = y[(y.index < issue) & (y.index >= hist.index[0])]
            r = res.apply(upto, refit=False)
            out.append(float(r.forecast(horizon).iloc[-1]))
        return _clip(np.array(out), train)


class Xgb(ModelSpec):
    def __init__(self):
        super().__init__("xgboost", "xgboost")

    def fit_predict(self, train, test, feats, horizon, y):
        import xgboost as xgb  # native API: no scikit-learn dependency

        params = dict(max_depth=4, eta=0.05, subsample=0.8, colsample_bytree=0.8, seed=SEED, nthread=2,
                      objective="reg:squarederror")
        booster = xgb.train(params, xgb.DMatrix(_xy(train, feats), label=train["y"].to_numpy()), num_boost_round=300)
        return _clip(booster.predict(xgb.DMatrix(_xy(test, feats))), train)


class Lgbm(ModelSpec):
    def __init__(self):
        super().__init__("lightgbm", "lightgbm")

    def fit_predict(self, train, test, feats, horizon, y):
        import lightgbm as lgb  # native API: no scikit-learn dependency

        params = dict(objective="regression", num_leaves=15, learning_rate=0.05, bagging_fraction=0.8,
                      bagging_freq=1, feature_fraction=0.8, seed=SEED, verbose=-1, num_threads=2)
        booster = lgb.train(params, lgb.Dataset(_xy(train, feats), label=train["y"].to_numpy()), num_boost_round=300)
        return _clip(booster.predict(_xy(test, feats)), train)


class CatBoost(ModelSpec):
    def __init__(self):
        super().__init__("catboost", "catboost")

    def fit_predict(self, train, test, feats, horizon, y):
        from catboost import CatBoostRegressor

        m = CatBoostRegressor(iterations=300, depth=4, learning_rate=0.05, random_seed=SEED, verbose=False,
                              thread_count=2, allow_writing_files=False)
        m.fit(_xy(train, feats), train["y"].to_numpy())
        return _clip(m.predict(_xy(test, feats)), train)


class Gru(ModelSpec):
    """Small GRU (hidden 16) on the last 48 hourly values, CPU, fixed epochs; torch only."""

    WINDOW, HIDDEN, EPOCHS = 48, 16, 40

    def __init__(self):
        super().__init__("gru", "torch")

    def fit_predict(self, train, test, feats, horizon, y):
        import torch

        torch.manual_seed(SEED)
        scale = float(train["y"].max()) or 1.0
        series = (y / scale)

        def windows(index):
            xs, keep = [], []
            for i, t in enumerate(index):
                w = series[(series.index < t)].iloc[-self.WINDOW:]
                if len(w) == self.WINDOW and not w.isna().any():
                    xs.append(w.to_numpy(dtype=np.float32))
                    keep.append(i)
            return np.array(xs, dtype=np.float32), keep

        Xtr, ktr = windows(train.index)
        Xte, kte = windows(test.index)
        if len(Xtr) < 48 or not len(Xte):
            raise ValueError("not enough complete windows")
        ytr = (train["y"].to_numpy()[ktr] / scale).astype(np.float32)

        class Net(torch.nn.Module):
            def __init__(s):
                super().__init__()
                s.gru = torch.nn.GRU(1, self.HIDDEN, batch_first=True)
                s.head = torch.nn.Linear(self.HIDDEN, 1)

            def forward(s, x):
                return s.head(s.gru(x.unsqueeze(-1))[0][:, -1]).squeeze(-1)

        net, opt = Net(), None
        opt = torch.optim.Adam(net.parameters(), lr=0.01)
        xt, yt = torch.from_numpy(Xtr), torch.from_numpy(ytr)
        for _ in range(self.EPOCHS):
            opt.zero_grad()
            loss = torch.nn.functional.l1_loss(net(xt), yt)
            loss.backward()
            opt.step()
        with torch.no_grad():
            p = net(torch.from_numpy(Xte)).numpy() * scale
        out = test["lag1"].to_numpy(dtype=float).copy()  # windows with gaps: no GRU value -> NaN below
        out[:] = np.nan
        out[kte] = p
        return _clip(out, train)


def registry() -> list[ModelSpec]:
    return [Persistence(), RidgeLags(), Sarima(), Xgb(), Lgbm(), CatBoost(), Gru()]
