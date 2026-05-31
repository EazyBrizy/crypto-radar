"use client";

import { useEffect } from "react";

import type { Locale } from "./locale";
import { translateText } from "./dictionary";

const textOriginals = new WeakMap<Text, string>();
const attributeOriginals = new WeakMap<Element, Map<string, string>>();
const translatedAttributes = ["aria-label", "placeholder", "title"];
const ignoredTags = new Set(["SCRIPT", "STYLE", "TEXTAREA", "NOSCRIPT"]);

export function DomLocalizer({ locale }: { locale: Locale }) {
  useEffect(() => {
    const root = document.body;
    if (!root) return;

    localizeTree(root, locale);

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === "characterData" && mutation.target.nodeType === Node.TEXT_NODE) {
          localizeTextNode(mutation.target as Text, locale);
          continue;
        }

        if (mutation.type === "attributes" && mutation.target instanceof Element) {
          localizeAttributes(mutation.target, locale);
          continue;
        }

        for (const node of mutation.addedNodes) {
          localizeTree(node, locale);
        }
      }
    });

    observer.observe(root, {
      attributes: true,
      attributeFilter: translatedAttributes,
      characterData: true,
      childList: true,
      subtree: true
    });

    return () => observer.disconnect();
  }, [locale]);

  return null;
}

function localizeTree(node: Node, locale: Locale) {
  if (node.nodeType === Node.TEXT_NODE) {
    localizeTextNode(node as Text, locale);
    return;
  }

  if (!(node instanceof Element) || ignoredTags.has(node.tagName)) return;

  localizeAttributes(node, locale);
  for (const child of Array.from(node.childNodes)) {
    localizeTree(child, locale);
  }
}

function localizeTextNode(node: Text, locale: Locale) {
  const parent = node.parentElement;
  if (!parent || ignoredTags.has(parent.tagName)) return;
  const current = node.textContent ?? "";
  const previousOriginal = textOriginals.get(node);
  const previousTranslation = previousOriginal ? translateText(previousOriginal, locale) : null;
  const original = previousOriginal && (current === previousOriginal || current === previousTranslation)
    ? previousOriginal
    : current;
  textOriginals.set(node, original);
  const translated = translateText(original, locale);
  if (node.textContent !== translated) node.textContent = translated;
}

function localizeAttributes(element: Element, locale: Locale) {
  if (ignoredTags.has(element.tagName)) return;

  let originals = attributeOriginals.get(element);
  if (!originals) {
    originals = new Map<string, string>();
    attributeOriginals.set(element, originals);
  }

  for (const attribute of translatedAttributes) {
    const value = element.getAttribute(attribute);
    if (!value) continue;

    const original = originals.get(attribute) ?? value;
    if (!originals.has(attribute)) originals.set(attribute, original);

    const translated = translateText(original, locale);
    if (value !== translated) element.setAttribute(attribute, translated);
  }
}
