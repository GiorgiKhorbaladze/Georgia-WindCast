import type { Freshness, WorkerState } from "./types";

export const LOCALES = ["ka", "en"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "ka";
export const LOCALE_COOKIE = "windcast_lang";

export function resolveLocale(value: string | undefined | null): Locale {
  return (LOCALES as readonly string[]).includes(value ?? "") ? (value as Locale) : DEFAULT_LOCALE;
}

export interface Dictionary {
  appName: string;
  tagline: string;
  nav: { dashboard: string; map: string; history: string; forecast: string; about: string };
  languageLabel: string;
  kpi: {
    totalWind: string;
    scopeNote: string;
    source: string;
    observedAt: string;
    retrievedAt: string;
    notReported: string;
    trackedLocations: string;
    trackedLocationsNote: string;
    ingestionStatus: string;
    forecastHorizon: string;
    forecastHorizonPending: string;
  };
  freshness: Record<Freshness, string>;
  worker: Record<WorkerState, string>;
  reasons: Record<string, string>;
  unavailable: string;
  apiUnreachable: string;
  sites: { title: string; coordinatesPending: string; noMw: string };
  dataTypes: {
    title: string;
    actual: [string, string];
    model: [string, string];
    forecast: [string, string];
    missing: [string, string];
  };
  history: { title: string; empty: string };
  planned: { title: string; body: string; issue: string };
  about: { title: string; paragraphs: string[] };
  timezoneNote: string;
  footer: string;
}

const ka: Dictionary = {
  appName: "GEORGIA WINDCAST",
  tagline: "ქარის გენერაციისა და მეტეოროლოგიური პირობების მონიტორინგი",
  nav: {
    dashboard: "მთავარი",
    map: "რუკა",
    history: "ისტორია",
    forecast: "პროგნოზი",
    about: "მონაცემების შესახებ",
  },
  languageLabel: "ენა",
  kpi: {
    totalWind: "ქარის ელექტროსადგურების ჯამური გენერაცია",
    scopeNote: "ფაქტობრივი ჯამური მაჩვენებელი საქართველოს მასშტაბით. სადგურების მიხედვით MW არ ქვეყნდება.",
    source: "წყარო",
    observedAt: "წყაროს დროის ნიშნული",
    retrievedAt: "მიღების დრო",
    notReported: "არ არის მითითებული",
    trackedLocations: "მონიტორინგის ლოკაციები",
    trackedLocationsNote: "მეტეოროლოგიური მოდელის მონაცემები, არა გენერაცია",
    ingestionStatus: "მონაცემთა მიღების სტატუსი",
    forecastHorizon: "მეტეოროლოგიური პროგნოზის ჰორიზონტი",
    forecastHorizonPending: "ამინდის წყარო ჯერ არ არის ჩართული",
  },
  freshness: {
    fresh: "აქტუალური",
    stale: "მოძველებული",
    unverified: "დროის ნიშნული დაუდასტურებელია",
    unavailable: "მიუწვდომელია",
  },
  worker: {
    running: "მუშაობს",
    stale: "კავშირი შეწყვეტილია",
    never_seen: "ჯერ არ გაშვებულა",
  },
  reasons: {
    ingestion_not_configured: "GSE-დან მონაცემთა მიღება ჯერ არ არის ჩართული. წყაროს ვალიდაცია მიმდინარეობს.",
  },
  unavailable: "მონაცემები მიუწვდომელია",
  apiUnreachable: "სერვერთან კავშირი ვერ დამყარდა",
  sites: {
    title: "ქარის ელექტროსადგურების ლოკაციები",
    coordinatesPending: "კოორდინატები გადამოწმების პროცესშია",
    noMw: "სადგურის დონეზე MW არ ჩანს: GSE მხოლოდ ჯამურ მაჩვენებელს აქვეყნებს.",
  },
  dataTypes: {
    title: "მონაცემთა კატეგორიები",
    actual: ["ფაქტობრივი გენერაცია", "MW, GSE, ჯამური"],
    model: ["მოდელური ქარის პირობები", "მ/წმ, ანალიზი, არა გაზომვა"],
    forecast: ["პროგნოზირებული ქარის პირობები", "მ/წმ, მოდელის გაშვებასთან მიბმული"],
    missing: ["დაკარგული ან მოძველებული", "აშკარად მონიშნული, არ ივსება"],
  },
  history: {
    title: "ჯამური გენერაციის ისტორია",
    empty: "ისტორია იწყება მონაცემთა ვალიდური მიღების დაწყებიდან. ჩანაწერები ჯერ არ არის.",
  },
  planned: {
    title: "განვითარების პროცესშია",
    body: "ეს გვერდი მომდევნო ეტაპზე დაემატება. საჩვენებელი ან სიმულირებული მონაცემები არ გამოიყენება.",
    issue: "იხილეთ შესაბამისი GitHub Issue",
  },
  about: {
    title: "მონაცემების შესახებ",
    paragraphs: [
      "ქარის ჯამური გენერაცია (MW) აღებულია სს „საქართველოს სახელმწიფო ელექტროსისტემის“ (GSE) საჯარო ვებგვერდიდან. GSE ცალკეული სადგურების გენერაციას არ აქვეყნებს და აპლიკაცია მას არ აფასებს.",
      "ლოკაციების ქარის მონაცემები მეტეოროლოგიური მოდელის პროდუქტია და არ წარმოადგენს ანემომეტრის გაზომვას. პროგნოზი მიბმულია მოდელის გაშვების დროს.",
      "ქარის სიჩქარის ზრდა გენერაციის პროპორციულ ზრდას არ ნიშნავს. MW გენერაციის პროგნოზი ამ ეტაპზე არ არის.",
      "ეს ინსტრუმენტი საინფორმაციოა და არ ასრულებს SCADA-ს ან დისპეჩერიზაციის ფუნქციას.",
    ],
  },
  timezoneNote: "დრო მითითებულია თბილისის დროით (UTC+04:00)",
  footer: "საინფორმაციო მონიტორინგი. არ წარმოადგენს ოპერატიულ ან დისპეჩერულ ინსტრუმენტს.",
};

const en: Dictionary = {
  appName: "GEORGIA WINDCAST",
  tagline: "Wind generation and meteorological monitoring",
  nav: { dashboard: "Dashboard", map: "Map", history: "History", forecast: "Forecast", about: "About Data" },
  languageLabel: "Language",
  kpi: {
    totalWind: "Total wind generation",
    scopeNote: "Actual national aggregate for Georgia. Per-plant MW is not published.",
    source: "Source",
    observedAt: "Source timestamp",
    retrievedAt: "Retrieved",
    notReported: "not reported",
    trackedLocations: "Tracked locations",
    trackedLocationsNote: "Meteorological model data, not generation",
    ingestionStatus: "Ingestion status",
    forecastHorizon: "Meteorological forecast horizon",
    forecastHorizonPending: "Weather source not yet enabled",
  },
  freshness: {
    fresh: "Fresh",
    stale: "Stale",
    unverified: "Timestamp unverified",
    unavailable: "Unavailable",
  },
  worker: { running: "Running", stale: "Not reporting", never_seen: "Not started yet" },
  reasons: {
    ingestion_not_configured: "GSE ingestion is not enabled yet. Source validation is in progress.",
  },
  unavailable: "Data unavailable",
  apiUnreachable: "Cannot reach the server",
  sites: {
    title: "Wind farm locations",
    coordinatesPending: "Coordinates pending verification",
    noMw: "No per-plant MW is shown: GSE publishes the national total only.",
  },
  dataTypes: {
    title: "Data categories",
    actual: ["Actual generation", "MW, GSE, national total"],
    model: ["Model wind conditions", "m/s, analysis, not measured"],
    forecast: ["Forecast wind conditions", "m/s, tied to model run"],
    missing: ["Missing or stale", "Explicitly marked, never filled"],
  },
  history: {
    title: "Aggregate generation history",
    empty: "History starts when valid ingestion begins. No records yet.",
  },
  planned: {
    title: "In development",
    body: "This page arrives in a later stage. No demo or simulated data is used.",
    issue: "See the related GitHub Issue",
  },
  about: {
    title: "About the data",
    paragraphs: [
      "Total wind generation (MW) comes from the public website of the Georgian State Electrosystem (GSE). GSE does not publish per-plant output and this application does not estimate it.",
      "Site wind values are meteorological model products, not anemometer measurements. Forecasts are tied to their model run time.",
      "Higher wind speed does not imply proportionally higher generation. No MW generation forecast is provided at this stage.",
      "This tool is informational and has no SCADA or dispatching function.",
    ],
  },
  timezoneNote: "Times shown in Tbilisi time (UTC+04:00)",
  footer: "Informational monitoring. Not an operational or dispatching tool.",
};

const DICTIONARIES: Record<Locale, Dictionary> = { ka, en };

export function getDictionary(locale: Locale): Dictionary {
  return DICTIONARIES[locale];
}
