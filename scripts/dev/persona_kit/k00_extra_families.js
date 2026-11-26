// K00: seven extra Demo Academy families, ported from docs/qa/2026-11-26-persona-usability/seed_more.js.
// Keeps the original seed_* ids so it upserts over a DB that already ran seed_more.js.
const A = "acad_demo_academy", now = new Date();
const L1 = "01M8BA9TYJB7ZHK6NSP89YQX9G", L2 = "01M8BA9V144TJQZFG3KQ8YD47X", P = "01M8BA9TY0HTQD6Z4FWR9HMTXE";
const fams = [
  ["Patel", "Anita Patel", [["Riya","2015-03-02",L2,"sat",""],["Dev","2018-07-19",L1,"sat",""]]],
  ["Okafor", "Chidi Okafor", [["Ada","2014-11-08",L2,"sat","Mild asthma; inhaler in bag"]]],
  ["Nguyen", "Linh Nguyen", [["Bao","2016-01-25",L1,"sat",""],["Mai","2013-09-14",L2,"wed",""]]],
  ["Garcia", "Elena Garcia", [["Diego","2017-05-30",L1,"sat","Peanut allergy (EpiPen)"]]],
  ["Kim", "Joon Kim", [["Hana","2015-12-01",L2,"sat",""],["Min","2019-02-17",L1,"wed",""]]],
  ["Brown", "Tasha Brown", [["Jayden","2014-06-22",L1,"sat","Wears glasses; sports goggles preferred"],["Zoe","2016-10-03",L1,"wed",""]]],
  ["Schmidt", "Karl Schmidt", [["Lena","2015-08-09",L2,"sat",""],["Felix","2017-04-11",L1,"sat",""],["Emil","2018-12-28",L1,"wed",""]]],
];
const pastSat = db.session_occurrences.find({academy_id:A, session_id:"demo_session_sat", kit:{$exists:false}}).sort({start_at:1}).toArray()
  .map(o=>o.occurrence_id).filter(id=>id && id.split(":")[1] < now.toISOString().slice(0,10));
let n = 0, att = 0;
fams.forEach(([last, parent, kids], fi) => {
  const pid = `seed_user_parent_${last.toLowerCase()}`;
  db.users.updateOne({user_id:pid},{$set:{user_id:pid,academy_id:A,created_at:now,updated_at:now,display_name:parent,name:parent,
    email:`${last.toLowerCase()}.family@example.com`,normalized_email:`${last.toLowerCase()}.family@example.com`,global_status:"active",
    is_active:true,phone:`555-01${20+fi}`,role:"parent",roles:["parent"],status:"active",stripe_customer_id:null}},{upsert:true});
  db.academy_memberships.updateOne({membership_id:`seed_membership_${last.toLowerCase()}`},{$set:{academy_id:A,membership_id:`seed_membership_${last.toLowerCase()}`,
    user_id:pid,roles:["parent"],status:"active",invited_by:"demo_user_owner",invited_at:now,accepted_at:now,created_at:now,updated_at:now}},{upsert:true});
  db.email_suppressions.updateOne({email:`${last.toLowerCase()}.family@example.com`},{$set:{email:`${last.toLowerCase()}.family@example.com`,reason:"hard_bounce",created_at:now}},{upsert:true});
  kids.forEach(([first, dob, level, cls, med]) => {
    const sid = `seed_student_${first.toLowerCase()}_${last.toLowerCase()}`;
    db.students.updateOne({student_id:sid},{$set:{academy_id:A,student_id:sid,first_name:first,last_name:last,full_name:`${first} ${last}`,date_of_birth:dob,
      emergency_contact_name:parent,emergency_contact_phone:`555-01${20+fi}`,medical_notes:med||"__none_declared__",skill_level:level===L2?"Intermediate":"Beginner",
      parent_id:pid,parent_user_id:pid,waiver_accepted:true,waiver_date:now,status:"active",is_deleted:false,created_at:now}},{upsert:true});
    db.enrollments.updateOne({enrollment_id:`seed_enrollment_${sid}`},{$set:{academy_id:A,enrollment_id:`seed_enrollment_${sid}`,session_id:`demo_session_${cls}`,
      student_id:sid,parent_id:pid,parent_user_id:pid,billing_type:"Standard",approval_status:"approved",status:"active",enrolled_at:new Date(now-35*864e5),is_deleted:false}},{upsert:true});
    db.student_level_progress.updateOne({progress_id:`seed_lp_${sid}`},{$set:{progress_id:`seed_lp_${sid}`,academy_id:A,completed_at:null,created_at:now,level_id:level,
      program_id:P,started_at:new Date(now-35*864e5),status:"active",student_id:sid}},{upsert:true});
    if (cls === "sat") pastSat.forEach((oc, i) => {
      const st = (n + i) % 7 === 3 ? "absent" : "present";
      // Keyed on (occurrence, student), not the loop index, so a re-run never duplicates a mark.
      db.attendance.updateOne({academy_id:A,occurrence_id:oc,student_id:sid},{$setOnInsert:{attendance_id:`seed_att_${sid}_${i}`},$set:{session_id:"demo_session_sat",
        marked_by:"demo_user_coach",marked_at:now,status:st,client_app_version:"demo-seed",entry_source:"enrollment"}},{upsert:true}); att++; });
    n++;
  });
});
print(`students +${n}, attendance +${att}, past sat occurrences ${pastSat.length}`);
