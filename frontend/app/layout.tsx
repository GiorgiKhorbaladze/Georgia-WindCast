import "./globals.css";
export const metadata = { title: "Georgia WindCast", description: "Georgia wind monitoring" };
export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
