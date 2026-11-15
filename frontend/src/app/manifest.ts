import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Georgia WindCast",
    short_name: "WindCast",
    description: "Georgia aggregate wind generation and site-level model wind",
    start_url: "/",
    display: "standalone",
    background_color: "#03070e",
    theme_color: "#03070e",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
