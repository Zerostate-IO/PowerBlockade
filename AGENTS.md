# PowerBlockade — agent working conventions

- **Roadmap is the source of truth** for direction and sequencing: read
  `ROADMAP.md` (especially "Work orders toward 1.0" and the milestone table
  under "Working conventions") before planning nontrivial work.
- **Branches and worktrees are named after roadmap milestones**: branch
  `wo/<milestone-slug>`, worktree `../pb-wt-<milestone-slug>`, per the table
  in ROADMAP.md. Sub-packets append suffixes; integration branches are
  `rel/vX.Y.Z`. Do not invent ad-hoc naming schemes.
- **GitHub flow**: topic branches + PRs into `main`; atomic commits with
  imperative subjects; never push `main` directly except single-commit doc
  amendments agreed with the maintainer; version bumps and CHANGELOG
  releases follow `docs/RELEASE_POLICY.md` and `RELEASE_AUTOMATION_GUIDE.md`
  (eight version surfaces + uv.lock; the release workflow validates them).
- **Verification culture**: performance claims must trace to committed
  artifacts under `docs/performance/results/`; benchmarks run via
  `scripts/benchmarks/dns53-benchmark.sh` (see its `--self-test`); external
  comparisons live in `docs/comparisons.md` with dated sources.
- **Sandboxing on dev boxes**: verification in throwaway `docker run --rm`
  containers only (no `powerblockade-*` names, no published host ports, no
  host bind-mounts — SELinux denies them; pipe via stdin). One live compose
  stack at a time; fixed container names are shared.
- **Secrets**: never commit or print values; new `.env` keys get documented
  in `.env.example` and the CHANGELOG release notes.
