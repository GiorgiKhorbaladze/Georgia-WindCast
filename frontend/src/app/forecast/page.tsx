import { PlannedPage } from "@/components/PlannedPage";
import { getI18n } from "@/lib/locale-server";

export default async function ForecastPage() {
  const { t } = await getI18n();
  return <PlannedPage t={t} title={t.nav.forecast} issue={7} />;
}
