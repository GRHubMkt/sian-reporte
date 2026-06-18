# SIAN · Reporte diario de leads

Dashboard estático que se actualiza solo todos los días a las **10:00 AM hora de Cancún**
mediante GitHub Actions. Muestra: hoy vs ayer, mes actual vs mes anterior, tendencia
diaria, embudo y fuentes. Solo datos agregados (sin información personal); los registros
de prueba/QA se excluyen automáticamente.

## Archivos
- `index.html` — la página (lee `data.json`). Se publica con GitHub Pages.
- `data.json` — los números del reporte (lo regenera el robot a diario).
- `generate.py` — consulta la base y reescribe `data.json`.
- `.github/workflows/daily.yml` — corre `generate.py` cada día a las 10:00 Cancún.

## Puesta en marcha (una sola vez)

1. **Agrega la credencial como Secret** (NUNCA la pongas en el código):
   Settings → Secrets and variables → Actions → New repository secret
   - Name: `DATABASE_URL`
   - Value: la cadena de conexión de solo lectura `postgresql://USUARIO:CONTRASEÑA@HOST/siandata?sslmode=require`

2. **Activa GitHub Pages:** Settings → Pages → Source: *Deploy from a branch* → Branch: `main` / carpeta `/ (root)`.
   El reporte queda en `https://grhubmkt.github.io/sian-reporte/`

3. **Primera corrida:** pestaña Actions → "Actualizar reporte SIAN" → *Run workflow* (o espera a las 10:00 AM).

## Notas de seguridad
- El repositorio es **público**: `index.html` y `data.json` son visibles para cualquiera. Contienen solo cifras agregadas, **sin nombres, teléfonos ni emails**.
- La cadena de conexión va **solo en el Secret** `DATABASE_URL`, jamás en el repo. El usuario de base debe ser de **solo lectura**.

## Zona horaria
El cron usa `0 15 * * *` (15:00 UTC = 10:00 en Cancún, UTC-5 todo el año).
