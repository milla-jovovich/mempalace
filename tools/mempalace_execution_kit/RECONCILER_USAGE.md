# Reconciler usage

## Plan an internal fold-in

```bash
python tools/mempalace_execution_kit/semantic_reconciler.py \
  --repo-root . \
  --policy tools/mempalace_execution_kit/reconcile_policy.mempalace.yaml \
  --mode internal \
  --action plan \
  --base-ref build/conversion-kit \
  --incoming-ref develop
```

## Apply a policy-driven fold-in

```bash
python tools/mempalace_execution_kit/semantic_reconciler.py \
  --repo-root . \
  --policy tools/mempalace_execution_kit/reconcile_policy.mempalace.yaml \
  --mode internal \
  --action apply \
  --base-ref build/conversion-kit \
  --incoming-ref develop
```

## GitHub Actions validation

The semantic reconciler is also wired through `.github/workflows/semantic-reconciler.yml` for push and pull-request validation.

Expected validation lanes:

- `semantic-reconciler`
- `runtime-validate`
- `projection-drift`

The workflow files must exist on `develop` for GitHub to recognize the lanes, while the conversion-kit branch supplies the executable reconciler/runtime/drift surfaces.

## Outputs

- `.codespaces/reconciliation-report.json`
- `.codespaces/reconciliation-plan.md`
- `.codespaces/manual-conflicts.json`

## Current policy intent

- semantic authority is reconciled first
- derived artifacts are regenerated, not hand-merged
- runtime verification follows regeneration
- unresolved atomic overlaps are surfaced as manual conflicts
