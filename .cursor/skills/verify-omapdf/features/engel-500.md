# Engel-500 keep-only extract

Leave only the **500,00€ Belastungen to Torsten Engel** on three personal N26 statements: delete every page that does not hold that hit, and on remaining pages redact every other transaction row. **This feature is not shippable.** `delete_pages` and true `redact` are not in `OP_TYPES` today (see `control-omapdf gaps`). Record later proofs here; do not claim a pass.

Ground truth (keep/delete sets, keep row bands, redact bands, chrome-to-retain, pass criteria) is **only**:

`/cursor/stores/bc-edf2aef7-00f6-4716-aad3-e4d4e3b9a39b/internal/final-validations/engel-500/SPEC.md`

Override the directory with `OMAPDF_VERIFY_ENGEL500` if needed. **Do not re-extract** text or bboxes from the PDFs. **Do not copy** `statement-2025-10.pdf`, `statement-2025-11.pdf`, or `statement-2025-12.pdf` into the public git repo.

## Sub-features

- `engel-find` locates hits by **Torsten Engel** + Belastungen + `-500,00€` + the IBAN/reference in SPEC.md — not by `500,00` alone.
- `engel-delete-pages` deletes every original page not in that file's keep set.
- `engel-redact-others` redacts every other transaction **row band** listed in SPEC.md on the kept pages.
- `engel-november-empty` handles statement-2025-11.pdf (0 Engel rows; all 12 pages would be deleted).
- `engel-cli` / `engel-mcp` / `engel-gtk` each apply the **same op batch** (or GTK ghosts that serialize to it). A pass on one surface does not count for the others.

## How to get to it (user POV)

Once the ops exist (planned in `docs/omapdf-preview-parity-spec.md` §2.2 `delete_pages`, §2.6 `redact`, §4 CLI/MCP):

- CLI: `omapdf apply statement.pdf --ops batch.json -o out.pdf` (or `omapdf pages … --delete` plus `omapdf redact …` when those wrappers ship). Always `-o`. Dry-run first.
- MCP: `delete_pages` and `redact` (planned; both default dry-run until `confirm: true`), or `apply_ops` with the same JSON.
- GTK: `omapdf edit copy.pdf --ops batch.json`, then the **Save** button (accessible name `Save`). Editor must load `delete_pages` / `redact` as ghosts; today `_load_proposals` ignores them.

User intent: find every Torsten Engel 500€ Belastung, drop pages without it, black every other transaction on what remains. Identity chrome stays (SPEC.md).

## Driving it with control-omapdf

Preconditions:

- **Blocked today.** `control-omapdf gaps` exits `2` with `missing_for_engel_500: delete_pages, redact`. Stop. Write that capture under evidence as `engel-500/not-shippable.json` if you need an artifact. Do not invent ink boxes or page extraction workarounds and call them this feature.
- When those ops exist: isolated launch + doctor ok; `OMAPDF_VERIFY_ENGEL500` points at the fixture dir; `SPEC.md` is present; the three PDFs are present **next to the spec**, not in git; copies exist under `$OMAPDF_VERIFY_DIR/work/` (copy at prove time, never into the repo).
- Payee spelling in the PDF is **`Torsten Engel`**. Search `Thorsten` returns nothing.
- Hits (from SPEC.md — do not re-scan): `statement-2025-10.pdf` page **9**; `statement-2025-12.pdf` pages **1** and **16**. **3 hits.**
- `statement-2025-11.pdf` has **0** Engel rows (12 pages). The p.9 `+500,00€` row is not a hit.
- Keep/delete sets and all redact/keep bands: read SPEC.md only.

Later recipe (do not run as a pass while ops are missing):

- **Copy fixtures into the run dir, not git.** `cp` the three PDFs to `$OMAPDF_VERIFY_DIR/work/engel/` from `$OMAPDF_VERIFY_ENGEL500`. Never `git add` them.
- **Build one atomic batch per file from SPEC.md** using **original** 1-based page numbers. Apply redacts before delete, **or** rewrite page numbers after delete (December p.16 → p.2). Spec rects are on the originals.
  - October keep `{9}`, delete `{1,2,3,4,5,6,7,8,10,11}`. Redact the four other row bands on p.9 from SPEC.md. Do not redact the Engel keep band `[43.80, 151.20, 551.46, 228.19]`.
  - December keep `{1,16}`, delete the other 18 pages. Redact other row bands on p.1 and p.16 from SPEC.md. Keep bands `[43.80, 538.35, 551.46, 615.34]` (p.1) and `[43.80, 325.80, 551.46, 402.79]` (p.16).
  - November keep `{}`, delete `{1…12}`. Planned `delete_pages` refuses a 0-page document. SPEC.md pass: **omit the file** or produce an explicit skip — do **not** keep the p.9 self-credit. Record whichever skip the shipped op actually implements.
- **CLI entry.** Dry-run `control-omapdf cli --capture engel-500/cli-oct-dry.json -- apply "$WORK/statement-2025-10.pdf" --ops "$WORK/oct.json" --dry-run --json`. Digest unchanged. Then write `-o` copies. Repeat for December. November: expect skip/error per shipped rules; capture it.
- **MCP entry.** Same JSON via `omapdf-mcp` `apply_ops` / planned `delete_pages`+`redact` with confirm after dry-run. Capture the RPC result separately (`engel-500/mcp-*.json`). Do not reuse the CLI capture as MCP proof.
- **GTK entry.** Copy a statement, `omapdf edit copy.pdf --ops batch.json`, click **Save**. Title contains the filename and `omapdf`. After Save, `omapdf read` the same copy. Record screenshot of the saved page plus read JSON. Do not treat `--ops` load without Save as a write.
- **Pass criteria (SPEC.md):** October output **1** page; December **2** pages. Each remaining page still has extractable `Torsten Engel` and `-500,00€`. Every SPEC.md redact-band payee/amount string is **gone** from `omapdf read` (not covered by ink). Statement chrome listed as retain may remain. November is omitted or empty, and the `+500,00€` credit is not kept as Engel.
- **Proof.** Per surface: dry-run digest, apply capture, `read --text-only` after, snapshots of remaining pages in the **private** evidence dir. Feature ID `engel-500`. Note the spec path and git commit of omapdf.

## Gotchas

- **Not shippable** until `delete_pages` and `redact` ship in schema + engine + CLI/MCP + GTK ghosts + tests. Overlay ink is not redact (`get_text()` would still return the payee).
- **Do not match `500,00` alone.** SPEC.md lists non-Engel `500,00` rows (PayPal Lastschrift, Gutschrift). A hit is Torsten Engel + Belastungen + `-500,00€` + IBAN/reference in the spec.
- Spelling is **Torsten**, not Thorsten.
- Do not re-extract bboxes; SPEC.md bands are the contract.
- Do not commit the PDFs. `.gitignore` lists the three filenames as a safety net.
- November deleting all 12 pages conflicts with planned “refuse to delete every page”. That conflict is part of the later proof, not a reason to keep a decoy 500€ row.
- CLI success does not verify MCP or GTK. Report skipped surfaces as skipped.
- Identity chrome is retained in this validation; a later privacy pass is out of scope (SPEC.md).
