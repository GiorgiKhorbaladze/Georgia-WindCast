import { PlannedPage } from "@/components/PlannedPage";
import { getI18n } from "@/lib/locale-server";

export default async function HistoryPage() {
  const { t } = await getI18n();
  return <PlannedPage t={t} title={t.nav.history} issue={7} />;
}
