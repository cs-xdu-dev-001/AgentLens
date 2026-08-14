import React from "./reactGlobal.js";

function createElement(type, props, key) {
  const nextProps = props ? { ...props } : {};
  if (key !== undefined) nextProps.key = key;
  return React.createElement(type, nextProps);
}

export const Fragment = React.Fragment;
export const jsx = createElement;
export const jsxs = createElement;
export const jsxDEV = createElement;
