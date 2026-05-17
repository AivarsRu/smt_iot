/**
 * Stage-form show/hide helper.
 *
 * Each fieldset row marked with ``data-show-when="<field>"`` and
 * ``data-show-value="<expected>"`` is shown only when the named form
 * control currently has the expected value. Checkboxes report ``on``
 * when checked and ``""`` otherwise. The form is always valid
 * server-side regardless of JS — this script only reduces visual noise.
 */
(function () {
  "use strict";

  function readValue(form, name) {
    const node = form.elements.namedItem(name);
    if (!node) return "";
    if (node.type === "checkbox") return node.checked ? "on" : "";
    if (node instanceof RadioNodeList) return node.value || "";
    return node.value || "";
  }

  function refresh(form) {
    form.querySelectorAll("[data-show-when]").forEach((field) => {
      const controlName = field.dataset.showWhen;
      // ``data-show-value`` is the primary trigger value; an optional
      // ``data-show-value-alt`` lets one row track two parent values
      // (e.g., a scope picker visible for both ``manual`` and ``preset``
      // threshold modes) without splitting it into duplicate markup.
      const expected = field.dataset.showValue;
      const expectedAlt = field.dataset.showValueAlt;
      const current = readValue(form, controlName);
      const visible = current === expected || (
        expectedAlt !== undefined && current === expectedAlt
      );
      field.hidden = !visible;
    });
  }

  function bindForm(form) {
    form.addEventListener("change", () => refresh(form));
    refresh(form);
  }

  function init() {
    document.querySelectorAll("form[data-stage-form]").forEach(bindForm);
    // Backwards-compat: the Stage 1 form still uses the old id.
    const legacy = document.getElementById("asset-create-form");
    if (legacy && !legacy.dataset.stageForm) bindForm(legacy);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
