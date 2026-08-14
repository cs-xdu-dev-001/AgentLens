import { fileURLToPath } from "node:url";
import babel from "@babel/core";
import { defineConfig } from "vite";

const { transformAsync } = babel;
const backendUrl = process.env.VITE_BACKEND_URL || "http://127.0.0.1:8010";
const jsxFileRE = /\.[jt]sx$/;
const modulePath = (relativePath) => fileURLToPath(new URL(relativePath, import.meta.url));

function isValidObjectKey(name) {
  return /^[A-Za-z_$][\w$]*$/.test(name);
}

function normalizeJsxText(value) {
  const lines = value.replace(/\r\n?/g, "\n").split("\n");
  return lines
    .map((line, index) => {
      let text = line.replace(/\t/g, " ");
      if (index > 0) text = text.replace(/^\s+/, "");
      if (index < lines.length - 1) text = text.replace(/\s+$/, "");
      return text;
    })
    .filter((line) => line.trim())
    .map((line, index, filtered) => (index < filtered.length - 1 ? `${line} ` : line))
    .join("");
}

function jsxClassicPlugin({ types: t }) {
  const reactMember = (name) => t.memberExpression(t.identifier("React"), t.identifier(name));

  const convertName = (name) => {
    if (t.isJSXIdentifier(name)) {
      const tagName = name.name;
      return /^[a-z]/.test(tagName) || tagName.includes("-")
        ? t.stringLiteral(tagName)
        : t.identifier(tagName);
    }
    if (t.isJSXMemberExpression(name)) {
      return t.memberExpression(convertName(name.object), t.identifier(name.property.name));
    }
    if (t.isJSXNamespacedName(name)) {
      return t.stringLiteral(`${name.namespace.name}:${name.name.name}`);
    }
    return t.stringLiteral("div");
  };

  const convertAttributeName = (name) => {
    if (t.isJSXIdentifier(name)) {
      return isValidObjectKey(name.name) ? t.identifier(name.name) : t.stringLiteral(name.name);
    }
    if (t.isJSXNamespacedName(name)) {
      return t.stringLiteral(`${name.namespace.name}:${name.name.name}`);
    }
    return t.stringLiteral(String(name.name || ""));
  };

  const convertAttributeValue = (value) => {
    if (!value) return t.booleanLiteral(true);
    if (t.isStringLiteral(value)) return value;
    if (t.isJSXExpressionContainer(value)) {
      return t.isJSXEmptyExpression(value.expression) ? t.booleanLiteral(true) : value.expression;
    }
    if (t.isJSXElement(value)) return convertElement(value);
    if (t.isJSXFragment(value)) return convertFragment(value);
    return value;
  };

  const convertChildren = (children) => {
    const output = [];
    for (const child of children) {
      if (t.isJSXText(child)) {
        const text = normalizeJsxText(child.value);
        if (text) output.push(t.stringLiteral(text));
        continue;
      }
      if (t.isJSXExpressionContainer(child)) {
        if (!t.isJSXEmptyExpression(child.expression)) output.push(child.expression);
        continue;
      }
      if (t.isJSXElement(child)) {
        output.push(convertElement(child));
        continue;
      }
      if (t.isJSXFragment(child)) {
        output.push(convertFragment(child));
        continue;
      }
      if (t.isJSXSpreadChild(child)) output.push(child.expression);
    }
    return output;
  };

  const convertProps = (attributes) => {
    if (!attributes.length) return t.nullLiteral();
    const props = attributes.map((attribute) => {
      if (t.isJSXSpreadAttribute(attribute)) return t.spreadElement(attribute.argument);
      return t.objectProperty(convertAttributeName(attribute.name), convertAttributeValue(attribute.value));
    });
    return t.objectExpression(props);
  };

  function convertElement(node) {
    return t.callExpression(reactMember("createElement"), [
      convertName(node.openingElement.name),
      convertProps(node.openingElement.attributes),
      ...convertChildren(node.children),
    ]);
  }

  function convertFragment(node) {
    return t.callExpression(reactMember("createElement"), [
      reactMember("Fragment"),
      t.nullLiteral(),
      ...convertChildren(node.children),
    ]);
  }

  return {
    name: "knowflow-jsx-classic",
    manipulateOptions(_options, parserOptions) {
      parserOptions.plugins = parserOptions.plugins || [];
      if (!parserOptions.plugins.includes("jsx")) parserOptions.plugins.push("jsx");
    },
    visitor: {
      JSXElement(path) {
        path.replaceWith(convertElement(path.node));
      },
      JSXFragment(path) {
        path.replaceWith(convertFragment(path.node));
      },
    },
  };
}

function reactJsxWithoutEsbuild() {
  return {
    name: "knowflow-react-jsx-without-esbuild",
    enforce: "pre",
    async transform(code, id) {
      const cleanId = id.split("?")[0];
      if (!jsxFileRE.test(cleanId)) return null;
      const result = await transformAsync(code, {
        filename: cleanId,
        babelrc: false,
        configFile: false,
        sourceMaps: true,
        plugins: [jsxClassicPlugin],
      });
      if (!result?.code) return null;
      const needsReactImport = result.code.includes("React.createElement") || result.code.includes("React.Fragment");
      const hasReactBinding = /\bimport\s+React\b|\bimport\s+\*\s+as\s+React\b|\bconst\s+React\b/.test(code);
      const nextCode = needsReactImport && !hasReactBinding
        ? `import React from "react";\n${result.code}`
        : result.code;
      return {
        code: nextCode,
        map: result.map || null,
      };
    },
  };
}

export default defineConfig({
  root: "react",
  plugins: [reactJsxWithoutEsbuild()],
  esbuild: false,
  optimizeDeps: {
    noDiscovery: true,
  },
  resolve: {
    alias: [
      { find: /^react\/jsx-runtime$/, replacement: modulePath("./react/src/vendor/reactJsxRuntimeGlobal.js") },
      { find: /^react\/jsx-dev-runtime$/, replacement: modulePath("./react/src/vendor/reactJsxRuntimeGlobal.js") },
      { find: /^react$/, replacement: modulePath("./react/src/vendor/reactGlobal.js") },
      { find: /^react-dom$/, replacement: modulePath("./react/src/vendor/reactDomGlobal.js") },
      { find: /^react-dom\/client$/, replacement: modulePath("./react/src/vendor/reactDomClientGlobal.js") },
    ],
  },
  build: {
    outDir: "../dist",
    emptyOutDir: true,
    minify: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": backendUrl,
      "/docs": backendUrl,
      "/redoc": backendUrl,
      "/openapi.json": backendUrl,
    },
  },
});
