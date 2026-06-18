#!/usr/bin/env python3
"""
Genera data.json para el reporte diario de leads de SIAN.
Lee la cadena de conexión SOLO desde la variable de entorno DATABASE_URL
(en GitHub se configura como Secret; nunca se guarda en el repo).
Produce únicamente datos agregados (sin PII) y excluye registros de prueba/QA.
"""
import os
import json
import datetime
import psycopg2

DSN = os.environ.get("DATABASE_URL")
if not DSN:
    raise SystemExit("Falta la variable de entorno DATABASE_URL")

# Filtro de datos de prueba/QA (se excluyen)
NOTTEST = """not (
  coalesce(customer_phone,'') ~* '^(eval-|audit|test-|post|posthc)'
  or customer_name ilike '%test%' or customer_name ilike 'Web Visitor%'
  or coalesce(customer_email,'') ilike '%@test.com'
  or contact_key ~ '^[+]?[0-9]{1,3}$'
  or (customer_name is null and customer_phone is null and customer_email is null)
)"""

Q_HEAD = f"""
with b as (
  select (first_contact_at at time zone 'America/Cancun')::date d,
    disposition, was_handed_off,
    coalesce(conversation_count,0) cc, coalesce(outbound_call_count,0) oc
  from public.lead_report where {NOTTEST}
), p as (select (timezone('America/Cancun',now()))::date today)
select to_char(p.today,'DD/MM/YYYY') today_lbl,
 count(*) filter (where d=p.today) l_hoy,
 count(*) filter (where d=p.today and disposition is null) act_hoy,
 count(*) filter (where d=p.today and was_handed_off) v_hoy,
 coalesce(sum(oc) filter (where d=p.today),0) call_hoy,
 coalesce(sum(cc) filter (where d=p.today),0) chat_hoy,
 count(*) filter (where d=p.today and disposition in ('no_answer','not_interested','spam','other')) ab_hoy,
 count(*) filter (where d=p.today-1) l_ayer,
 count(*) filter (where d=p.today-1 and disposition is null) act_ayer,
 count(*) filter (where d=p.today-1 and was_handed_off) v_ayer,
 coalesce(sum(oc) filter (where d=p.today-1),0) call_ayer,
 coalesce(sum(cc) filter (where d=p.today-1),0) chat_ayer,
 count(*) filter (where d=p.today-1 and disposition in ('no_answer','not_interested','spam','other')) ab_ayer,
 count(*) filter (where d>=date_trunc('month',p.today)::date and d<=p.today) l_mtd,
 count(*) filter (where d>=date_trunc('month',p.today)::date and d<=p.today and was_handed_off) v_mtd,
 coalesce(sum(oc) filter (where d>=date_trunc('month',p.today)::date and d<=p.today),0) call_mtd,
 coalesce(sum(cc) filter (where d>=date_trunc('month',p.today)::date and d<=p.today),0) chat_mtd,
 count(*) filter (where d>=date_trunc('month',p.today - interval '1 month')::date and d<date_trunc('month',p.today)::date) l_pm,
 count(*) filter (where d>=date_trunc('month',p.today - interval '1 month')::date and d<date_trunc('month',p.today)::date and was_handed_off) v_pm,
 coalesce(sum(oc) filter (where d>=date_trunc('month',p.today - interval '1 month')::date and d<date_trunc('month',p.today)::date),0) call_pm,
 coalesce(sum(cc) filter (where d>=date_trunc('month',p.today - interval '1 month')::date and d<date_trunc('month',p.today)::date),0) chat_pm,
 count(*) filter (where d>=date_trunc('month',p.today - interval '1 month')::date and d<=(p.today - interval '1 month')::date) l_pm_mtd,
 to_char(date_trunc('month',p.today),'MM/YYYY') mes_act,
 to_char(date_trunc('month',p.today - interval '1 month'),'MM/YYYY') mes_ant
from b,p group by p.today
"""

Q_DAILY = f"""
select to_char(d,'DD/MM') lbl, count(*) leads, count(*) filter (where ho) ventas
from ( select (first_contact_at at time zone 'America/Cancun')::date d, was_handed_off ho
       from public.lead_report where {NOTTEST} ) x
where d >= (timezone('America/Cancun',now())::date - 20)
group by d order by d
"""

Q_FUNNEL = f"""
select count(*) leads,
 count(*) filter (where disposition is null) activos,
 count(*) filter (where disposition in ('no_answer','not_interested','spam','other')) abandono,
 count(*) filter (where disposition='duplicate') duplicado,
 count(*) filter (where was_handed_off) ventas,
 count(*) filter (where odoo_won) ganados
from public.lead_report where {NOTTEST}
"""

Q_SRC = f"""
with x as (select source, (first_contact_at at time zone 'America/Cancun')::date d, disposition, was_handed_off
           from public.lead_report where {NOTTEST}),
     p as (select (timezone('America/Cancun',now()))::date today)
select coalesce(source,'(sin fuente)') fuente,
 count(*) filter (where d>=date_trunc('month',p.today)::date) mtd,
 count(*) filter (where d>=date_trunc('month',p.today)::date and disposition is null) act,
 count(*) filter (where d>=date_trunc('month',p.today)::date and was_handed_off) ventas,
 count(*) total
from x,p group by 1 order by total desc
"""


def rows(cur, sql):
    cur.execute(sql)
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def i(v):
    return int(v) if v is not None else 0


def main():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    h = rows(cur, Q_HEAD)[0]
    daily = rows(cur, Q_DAILY)
    f = rows(cur, Q_FUNNEL)[0]
    src = rows(cur, Q_SRC)
    cur.close()
    conn.close()

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-5)))
    data = {
        "generado_en": now.strftime("%d/%m/%Y %H:%M") + " (Cancún)",
        "today_lbl": h["today_lbl"],
        "mes_act": h["mes_act"], "mes_ant": h["mes_ant"],
        "hoy": {"leads": i(h["l_hoy"]), "activos": i(h["act_hoy"]), "ventas": i(h["v_hoy"]),
                "llamadas": i(h["call_hoy"]), "chats": i(h["chat_hoy"]), "abandono": i(h["ab_hoy"])},
        "ayer": {"leads": i(h["l_ayer"]), "activos": i(h["act_ayer"]), "ventas": i(h["v_ayer"]),
                 "llamadas": i(h["call_ayer"]), "chats": i(h["chat_ayer"]), "abandono": i(h["ab_ayer"])},
        "mtd": {"leads": i(h["l_mtd"]), "ventas": i(h["v_mtd"]), "llamadas": i(h["call_mtd"]), "chats": i(h["chat_mtd"])},
        "pm_full": {"leads": i(h["l_pm"]), "ventas": i(h["v_pm"]), "llamadas": i(h["call_pm"]), "chats": i(h["chat_pm"])},
        "pm_mtd_leads": i(h["l_pm_mtd"]),
        "funnel": {"leads": i(f["leads"]), "activos": i(f["activos"]), "abandono": i(f["abandono"]),
                   "duplicado": i(f["duplicado"]), "ventas": i(f["ventas"]), "ganados": i(f["ganados"])},
        "fuentes": [{"fuente": r["fuente"], "mtd": i(r["mtd"]), "act": i(r["act"]),
                     "ventas": i(r["ventas"]), "total": i(r["total"])} for r in src],
        "daily": [{"lbl": r["lbl"], "leads": i(r["leads"]), "ventas": i(r["ventas"])} for r in daily],
    }

    with open("data.json", "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    print("data.json actualizado:", data["generado_en"], "| leads MTD:", data["mtd"]["leads"])


if __name__ == "__main__":
    main()
