# Application localization

English (`en`) is the default. `i18n.js` explicitly allows English, German, French,
Spanish, Italian, Dutch, Polish and Portuguese. The selection is stored in
`localStorage['orqelis.language']`; the server session is independent of this setting.
Dates and monetary amounts use `Intl` with the selected locale.

The JSON catalogs use English source messages as keys, following the gettext
convention. Keep each complete message together and use numbered placeholders,
for example `t('A clearer view, {0}.', name)`. Do not concatenate translated words
to construct new sentences. Existing layout fragments are retained where the
original markup splits headings or links.

Use `t()` for plain text; escape its result before inserting it into HTML.
`htmlMessage()` escapes catalog text and then inserts already-safe HTML values.
Continue to escape user-controlled interpolation values with `esc()`.
Never store HTML in a catalog, use translated text as an API enum/identifier,
or look up tender text, source excerpts, filenames, company names or profile values
as translation keys. `I18N.generated()` is restricted to application-generated
assessment, notification and error messages; their captured source values remain
unchanged. Stored evidence, decisions and exports retain their original semantics.

Static shell text uses `data-i18n`; accessible labels use `data-i18n-label`.
Language changes reload the page and preserve the stored preference and server
session. Unsaved form edits are not persisted across that reload.
Original legal documents remain explicitly identified as English; their surrounding
navigation and language control are localized. Source documents remain original.

To add a language, add its code/native name to `i18n.js`, copy every key from `en.json`
to a new catalog, translate values while preserving every `{n}` placeholder, and
extend the language lists in the regression tests. Missing catalogs fail back to
English. Missing message keys are available through `I18N.missing` for QA.

Validation:

```sh
python -m pytest
node --test tests/i18n.test.cjs
python -m scripts.check_i18n_browser
```

Initial translations were generated from application-owned UI messages only and
reviewed for core authentication, procurement terminology and evidence-state
distinctions. Further native-speaker review is advisable before claiming editorial
or legally certified translations. No external translation service is used at runtime.
