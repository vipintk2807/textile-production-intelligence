# Domain rules, decisions and assumptions

This file records how the application resolves the items the project documents
left open. **None of these has been validated against a real textile factory.**
They are explicit, documented defaults chosen to avoid misleading numbers. All
example data is synthetic.

## Established rules (implemented and tested)

| Area | Rule |
|---|---|
| Units | Controlled `UnitOfMeasure` table (seeded: `kg`, `m`, `pcs`; extend in the admin site). No conversion is ever performed. Quantities are compared/summed only when the unit codes are identical; reports and dashboard group by unit. |
| Quantities | `DecimalField(max_digits=14, decimal_places=3)`, i.e. up to 99,999,999,999.999. Never floats. Source values are never rounded on storage. |
| Missing vs zero | A production target may be **missing** (blank, stored as NULL) or a genuine **0**. A missing target is never treated as zero. Actual output is required (0 is valid). |
| Target ownership | The target belongs to each *production record*, not to the order, so several records never repeat one order-level target. |
| Target achievement | `actual / target x 100`, only for a target > 0 and identical units. Otherwise "Not available" with a reason. |
| Variance | `actual - target`. Available for a zero target. Negative = below target. |
| Aggregation | `sum(actual) / sum(target) x 100` over **records that have a target**. Output on records without a target is shown in "Actual output (all records)" but excluded from achievement and variance (and counted in a note). Percentages are never averaged. |
| Rounding | Calculations use unrounded Decimals. Percentages display with 2 decimals (half-up); quantities with trailing zeros trimmed. CSV uses 2 dp (percent) and 3 dp (quantities). |
| Batch/order | A batch always belongs to one order; a record that stores both must use the batch's own order (form, model `clean()`, and a `save()` guard). A batch's unit must equal its order's unit. |
| Deletion | All foreign keys are `PROTECT`. Orders/batches with linked records cannot be deleted (change status instead). Production, downtime and quality records have no delete action in the interface: correct them by editing. |
| Downtime | Start and end timestamps (timezone-aware, configured zone, default `Asia/Kolkata`) are authoritative; duration is derived, never stored. End must be strictly after start. Cross-midnight events are valid. Incomplete events are **not** supported. |
| Downtime attribution | An event contributes only the part overlapping the selected period (clipping). Date filters are inclusive: `[start 00:00, end+1 day 00:00)` local time. |
| Downtime totals | Two labelled metrics: *sum of recorded event durations* (overlap counted more than once) and *unique elapsed downtime* (union of intervals). Overlapping pairs are counted and flagged. The model has no machine field, so overlaps are warnings, not errors. |
| Quality records | Event-level: each record is a *newly identified* quantity (not cumulative). Rework and rejection are separate types. They are never added to or subtracted from production output. No reconciliation (inspected = accepted + reworked + rejected) is assumed. |
| Quality rates | **Not calculated.** No inspected/accepted quantity is recorded and no denominator has been approved. The UI shows "Not available". `services/quality.quality_rate()` exists and is tested so an approved denominator can be plugged in later. |
| Statuses | Order and batch: `Planned`, `In progress`, `Completed`, `Cancelled`. New records start as Planned. Allowed transitions: Planned -> In progress/Cancelled; In progress -> Completed/Cancelled/Planned; Completed -> In progress; Cancelled -> Planned. Enforced on the server. |
| Authentication | None. Intended for **trusted local use**; do not expose to untrusted networks. CSRF protection is on. |
| Concurrency | Single-user local operation; no record locking (last write wins). |
| Shifts | Not implemented. `period_label` is a free-text optional label only; the application does not infer or invent shift times. |

## Provisional assumptions (confirm with real users)

1. **Completed quantity** for *remaining order quantity* = sum of recorded
   actual output in the order's own unit. This is a provisional definition,
   not an authoritative measure (actual output is not assumed to be acceptable
   output). Remaining = order quantity - completed; a negative result is kept
   and flagged as over-production, never clamped to zero. Records in other
   units are excluded and counted.
2. **Downtime categories** (Mechanical, Electrical / power, Material
   unavailable, Setup / changeover, Other) are a neutral starting list, not an
   industry standard.
3. **Initial unit list** (kg, m, pcs) is a small starting catalogue.
4. **Reporting attribution** is by overlap (clipping), chosen because it
   prevents double counting across days.
5. **Dashboard "Orders to investigate"** flags (a) recorded output above order
   quantity and (b) orders marked Completed whose recorded output is below the
   order quantity. These are prompts, not verdicts.

## Still unresolved (not implemented because undefined)

- Rework / rejection rate denominators and repeat-inspection handling.
- Whether one order may legitimately contain output in several units (the
  application allows it and keeps the units separate).
- Shift schedules and shift-based KPIs; efficiency / OEE measures.
- Record-correction audit trail and role-based permissions.

## Synthetic data

`python manage.py load_demo_data` creates three clearly labelled `SYN-` orders
with fixed values covering: below / equal / above target, a missing target, a
zero target, mixed units, a cross-midnight downtime event, overlapping
downtime, rework and rejection, and over-production. See the command's
docstring. Expected results (for example an 85% achievement on SYN-BAT-001)
are hand-calculated in the tests.
