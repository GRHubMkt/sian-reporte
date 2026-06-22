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

# Inversion de la campana de Meta (MSG). Si existe el secret META_ACCESS_TOKEN,
# se obtiene en vivo desde la Graph API; si no, se usa este valor de respaldo.
META_SPEND_MXN = 6954.91          # respaldo (se usa solo si no hay token de Meta)
META_SPEND_DATE = "17/06/2026"
META_CAMPAIGN_ID = "120246259039590082"  # Campana MSG en Meta Ads
META_API_VERSION = "v25.0"


def fetch_meta_spend():
    """Gasto lifetime de la campana MSG desde la Graph API de Meta.
    Devuelve (spend_float, True) si lo logra; (None, False) si no hay token o falla."""
    token = os.environ.get("META_ACCESS_TOKEN")
    if not token:
        return None, False
    try:
        import urllib.request
        import urllib.parse
        qs = urllib.parse.urlencode({"fields": "spend", "date_preset": "maximum", "access_token": token})
        url = f"https://graph.facebook.com/{META_API_VERSION}/{META_CAMPAIGN_ID}/insights?{qs}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        data_rows = payload.get("data", [])
        if data_rows and data_rows[0].get("spend") is not None:
            return round(float(data_rows[0]["spend"]), 2), True
        print("Aviso: respuesta de Meta sin 'spend':", payload)
    except Exception as e:
        print("Aviso: no se pudo obtener el gasto de Meta:", e)
    return None, False

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
 count(*) filter (where odoo_won) ganados,
 count(*) filter (where odoo_probability >= 50) hot50,
 count(*) filter (where odoo_probability >= 70) hot70
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

Q_SANKEY = f"""
with x as (
  select source,
    coalesce(ai_handled,false) ai,
    case when disposition is null then 'activo' when disposition='duplicate' then 'dup' else 'aband' end bucket,
    (disposition is null) activo,
    coalesce(outbound_call_count,0) oc,
    was_handed_off
  from public.lead_report where {NOTTEST}
    and (first_contact_at at time zone 'America/Cancun')::date >= (timezone('America/Cancun',now()))::date - 6
)
select coalesce(source,'(sin fuente)') fuente, count(*) total,
 count(*) filter (where ai) ai, count(*) filter (where not ai) sin_ai,
 count(*) filter (where ai and bucket='activo') ai_activo,
 count(*) filter (where ai and bucket='aband') ai_aband,
 count(*) filter (where ai and bucket='dup') ai_dup,
 count(*) filter (where not ai and bucket='activo') sinai_activo,
 count(*) filter (where not ai and bucket='aband') sinai_aband,
 count(*) filter (where not ai and bucket='dup') sinai_dup,
 count(*) filter (where activo and oc>0) call,
 count(*) filter (where activo and oc=0) chat,
 count(*) filter (where activo and oc>0 and was_handed_off) call_cer,
 count(*) filter (where activo and oc>0 and not was_handed_off) call_sin,
 count(*) filter (where activo and oc=0 and was_handed_off) chat_cer,
 count(*) filter (where activo and oc=0 and not was_handed_off) chat_sin
from x group by 1 order by total desc
"""

# Detalle de leads SIN datos personales (no se incluye nombre, telefono ni email).
_DET_COLS = """
 coalesce(nullif(odoo_lead_id,''),'-') ref,
 to_char((first_contact_at at time zone 'America/Cancun'),'DD/MM') fecha,
 coalesce(source,'(sin fuente)') fuente,
 coalesce(odoo_stage,'(sin etapa)') etapa,
 case when disposition is null then 'Activo' else disposition end estatus,
 coalesce(round(odoo_probability)::int,0) prob,
 coalesce(nullif(odoo_salesperson,''),'(sin asignar)') cerrador
"""

Q_DET_NUEVOS = f"""
select {_DET_COLS}
from public.lead_report
where {NOTTEST}
 and (first_contact_at at time zone 'America/Cancun')::date = (timezone('America/Cancun',now()))::date
order by odoo_probability desc nulls last, last_activity_at desc nulls last
"""

Q_DET_VENTAS = f"""
select {_DET_COLS}
from public.lead_report
where {NOTTEST} and was_handed_off
order by last_activity_at desc nulls last
limit 80
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
    sk = rows(cur, Q_SANKEY)
    det_nuevos = rows(cur, Q_DET_NUEVOS)
    det_ventas = rows(cur, Q_DET_VENTAS)
    cur.close()
    conn.close()

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-5)))
    sk_desde = now.date() - datetime.timedelta(days=6)
    sankey_periodo = "{} – {} (últimos 7 días)".format(sk_desde.strftime("%d/%m"), now.strftime("%d/%m"))
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
        "sankey": [{
            "fuente": r["fuente"], "total": i(r["total"]), "ai": i(r["ai"]), "sin_ai": i(r["sin_ai"]),
            "ai_activo": i(r["ai_activo"]), "ai_aband": i(r["ai_aband"]), "ai_dup": i(r["ai_dup"]),
            "sinai_activo": i(r["sinai_activo"]), "sinai_aband": i(r["sinai_aband"]), "sinai_dup": i(r["sinai_dup"]),
            "call": i(r["call"]), "chat": i(r["chat"]),
            "call_cer": i(r["call_cer"]), "call_sin": i(r["call_sin"]),
            "chat_cer": i(r["chat_cer"]), "chat_sin": i(r["chat_sin"]),
        } for r in sk],
        "hot": {"p50": i(f["hot50"]), "p70": i(f["hot70"])},
        "sankey_periodo": sankey_periodo,
        "detalle_nuevos": [{"ref": r["ref"], "fecha": r["fecha"], "fuente": r["fuente"], "etapa": r["etapa"],
                            "estatus": r["estatus"], "prob": i(r["prob"]), "cerrador": r["cerrador"]} for r in det_nuevos],
        "detalle_ventas": [{"ref": r["ref"], "fecha": r["fecha"], "fuente": r["fuente"], "etapa": r["etapa"],
                            "estatus": r["estatus"], "prob": i(r["prob"]), "cerrador": r["cerrador"]} for r in det_ventas],
    }

    meta_leads = next((i(r["total"]) for r in sk if r["fuente"] == "meta_ad"), 0)
    live_spend, auto = fetch_meta_spend()
    spend = live_spend if live_spend is not None else round(META_SPEND_MXN, 2)
    updated = now.strftime("%d/%m/%Y") if auto else META_SPEND_DATE
    data["meta"] = {
        "spend": spend,
        "updated": updated,
        "leads": meta_leads,
        "cpl": round(spend / meta_leads, 2) if meta_leads else 0,
        "auto": auto,
    }

    with open("data.json", "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    print("data.json actualizado:", data["generado_en"], "| leads MTD:", data["mtd"]["leads"])


if __name__ == "__main__":
    main()
