// K09 (S20, partial): the busy parent owes this month's tuition for Alex, so
// Home shows an amount due. Reopens the base seed's paid invoice for Alex this
// month and drops its cash payment; re-running the base seed restores it.
const A = "acad_demo_academy", now = new Date();
const period = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;
const key = `alex_${period.replace("-", "_")}`;
const due = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 7));
const r = db.invoices.updateOne({academy_id:A, invoice_id:`demo_invoice_${key}`},
  {$set:{status:"open", balance_due_cents:8000, due_date:due, updated_at:now}});
db.payment_allocations.deleteMany({academy_id:A, allocation_id:`demo_allocation_${key}`});
db.ledger_payments.deleteMany({academy_id:A, payment_id:`demo_payment_${key}`});
print(`k09: demo_invoice_${key} ${r.matchedCount ? "open, $80.00 due" : "not found (run the base demo seed first)"}`);
