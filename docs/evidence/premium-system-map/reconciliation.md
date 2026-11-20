# GSE national figures reconciliation

Review date 20 November 2026, Asia/Tbilisi. The audit uses the immutable [balance archive](https://github.com/GiorgiKhorbaladze/Georgia-WindCast/blob/ae1fe3f683741a530be9dba9003080c8418ea2d3/balance/2026/11/2026-11-20.csv) and [wind archive](https://github.com/GiorgiKhorbaladze/Georgia-WindCast/blob/ae1fe3f683741a530be9dba9003080c8418ea2d3/gse/2026/11/2026-11-20.csv) at data commit `ae1fe3f683741a530be9dba9003080c8418ea2d3`. The 290 source labels run from 04:00 through 18:27 Tbilisi. All figures are three-minute average power in MW.

## Archived values

| Source time (Tbilisi) | Hydro | Thermal | Wind | Solar | Generation | Consumption | Gross import | Gross export | Signed difference |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 15:54 | 1305.245483 | 404.346008 | −0.065 | 8.629999 | 1717.505127 | 1964.221069 | 222.636745 | 28.402201 | −52.481398 |
| 16:00 | 1420.197998 | 413.924835 | −0.065 | 8.629999 | 1841.357788 | 1975.141113 | 102.588276 | 19.094099 | −50.289148 |
| 16:09 | 1537.552246 | 422.547485 | −0.075 | 8.629999 | 1968.654785 | 1937.714600 | 18.299999 | 1.229059 | +48.011125 |
| 17:12 | 1602.259766 | 424.108429 | −0.071 | 8.629999 | 2034.683594 | 2025.301025 | 18.299999 | 10.714442 | +16.968126 |

The signed difference is generation + gross import − gross export − consumption. Absolute differences exceeded 1 MW in **195 of 290** periods and 10 MW in **83 of 290**. The exact median on this pin is **4.3114845 MW**, compared with about 4.40 MW in the independent review. The maximum is **52.481398 MW**. The generation subtotal comparison is separate. Hydro + thermal + wind + solar was 0.243600 MW above published total generation at 17:12, and differed by more than 1 MW in 84 periods. At 16:09 the generation subtotal was within 0.000055 MW even though the national difference was over 48 MW.

The 290 wind records matched their balance records on source label, retrieval timestamp, payload SHA-256 and unrounded wind MW. The 17:12 record was retrieved at 17:15:34.824454 Tbilisi. The elapsed time from the source label to collector retrieval across the sample ranged from 213 to 962 seconds, with a median of 579 seconds. This measures collector delay, not measurement timing within GSE. The 17:12 generation and consumption records carry non-confirming source flags. The official meaning of those flags is unverified. Neither receipt lag nor quality flags establish a causal explanation. The archive stores all eight values together under each label. It cannot demonstrate that upstream measurements were simultaneous.

## Original XML evidence and limits

The existing checked-in GSE originals for [15 November 00:09](../../../backend/tests/fixtures/gse/real_act_15112026_0009.xml) and [15 November 00:03](../../../backend/tests/fixtures/gse/real_nre_15112026_0003.xml) provide direct evidence of source row selection and sign. Both files have an explicit three-minute export label. GSE supplies named individual `Intercha` rows in one block with a zero `IntchSum`. The other three blocks in these examples have only subtotals. The collector uses individual rows where present and the subtotal otherwise. Positive signs contribute to gross import, negative signs contribute by magnitude to gross export. The originals contain no duplicate block/kind/identifier among the applicable rows. They show that a subtotal can differ from its individual rows and that incomplete line coverage prevents whole-network line reconciliation. A non-confirming individual quality flag appears in both records. Substitution semantics and asset assignments are still unverified.

At 00:09, the selected rows yield 73.393583 MW imports, zero exports and +0.000151 MW arithmetic difference. At 00:03, they yield 32.746205 MW imports, 30.897966 MW exports and −12.512113 MW difference directly from the source fields and selection rule. A subtotal-only calculation leaves −45.258318 MW at 00:03. The fixtures therefore confirm that the source fields and documented aggregation rule can produce a discrepancy before rounding, storage or rendering. They do not identify why the reported fields disagree or validate line coverage for 20 November.

Attempts to retrieve the exact 20 November XML for 15:54, 16:09 and 17:12 from the documented GSE export host received a cloud proxy CONNECT denial. The public GSE site received the same denial. No original XML or same-timestamp operator page was obtained for those periods. The pinned wind/balance archive hash match cannot substitute for the source bytes. Source timing, quality semantics, omitted lines and the interpretation of individual rows versus subtotals remain hypotheses for those periods. No measurement, sign or archive row was adjusted. No new collection was enabled.

## Reproduce the archive arithmetic

Fetch the data ref in the repository and run the following from its root. The reads use the pinned commit even if the branch has advanced.

```sh
git fetch origin data
python - <<'PY'
import csv
from decimal import Decimal
from statistics import median
from subprocess import check_output

commit = "ae1fe3f683741a530be9dba9003080c8418ea2d3"
def records(kind):
    blob = f"{commit}:{kind}/2026/11/2026-11-20.csv"
    return list(csv.DictReader(check_output(["git", "show", blob], text=True).splitlines()))

balance = records("balance")
wind = {row["period_label_utc"]: row for row in records("gse")}
differences = []
for row in balance:
    generation, imports, exports, load = (
        Decimal(row[f"{key}_mw"]) for key in ("generation", "import", "export", "consumption")
    )
    differences.append(abs(generation + imports - exports - load))
    match = wind[row["period_label_utc"]]
    for key in ("period_label_local", "retrieved_at_utc", "payload_sha256"):
        assert row[key] == match[key]
    assert Decimal(row["wind_mw"]) == Decimal(match["value_mw"])
print(len(balance), sum(d > 1 for d in differences), sum(d > 10 for d in differences),
      median(differences), max(differences))
PY
```
