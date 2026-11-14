import { PlannedPage } from "@/components/PlannedPage";
import { getI18n } from "@/lib/locale-server";

export default async function MapPage() {
  const { t } = await getI18n();
  return <PlannedPage t={t} title={t.nav.map} issue={6} />;
}
