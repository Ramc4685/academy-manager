// K09 (S20, S57): the busy parent owes this month's tuition for both children,
// with a sibling discount on Alex, so Home and Payments show one amount due
// ($80.00 Sam + $80.00 Alex - $20.00 sibling discount = $140.00). Last month
// stays paid in cash from the base seed. Reopens the base seed's paid
// invoices for this month and drops their cash payments; re-running the base
// seed restores them (the kit discount line then no longer adds up, so the
// summary falls back to one line per child until K09 runs again).
const A = "acad_demo_academy", now = new Date();
const period = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;
const due = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 7));
const open = (child, total, discount) => {
  const key = `${child}_${period.replace("-", "_")}`;
  const r = db.invoices.updateOne({academy_id:A, invoice_id:`demo_invoice_${key}`},
    {$set:{status:"open", subtotal_cents:8000, discount_cents:discount, total_cents:total,
           balance_due_cents:total, due_date:due, updated_at:now}});
  db.payment_allocations.deleteMany({academy_id:A, allocation_id:`demo_allocation_${key}`});
  db.ledger_payments.deleteMany({academy_id:A, payment_id:`demo_payment_${key}`});
  return r.matchedCount;
};
const sam = open("sam", 8000, 0);
const alex = open("alex", 6000, 2000);
db.invoice_lines.updateOne({academy_id:A, line_id:`kit_line_alex_${period.replace("-", "_")}_sibling`},
  {$set:{academy_id:A, line_id:`kit_line_alex_${period.replace("-", "_")}_sibling`,
         invoice_id:`demo_invoice_alex_${period.replace("-", "_")}`, line_type:"discount",
         description:"Sibling discount", quantity:1, unit_amount_cents:-2000, amount_cents:-2000,
         source_type:"tuition_discount", source_id:"kit_discount_sibling", category:"sibling",
         discount_kind:"fixed", created_at:now}}, {upsert:true});
print(`k09: ${sam && alex ? "Sam $80.00 + Alex $80.00 - $20.00 sibling discount = $140.00 due" : "invoices not found (run the base demo seed first)"}`);
