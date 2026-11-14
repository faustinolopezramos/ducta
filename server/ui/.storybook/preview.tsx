import type { Preview } from "@storybook/react";
// Carga el tema global de Ducta (tokens + estilos) para que los componentes
// se rendericen con la identidad correcta en Storybook y en los previews del sync.
import "../src/index.css";

const preview: Preview = {
  parameters: {
    layout: "centered",
    controls: {
      matchers: { color: /(background|color)$/i, date: /Date$/i },
    },
  },
};

export default preview;
