# Catàleg local d'hospitals

- `catalog.json`: hospitals públics o integrats en xarxa pública del Catálogo Nacional de Hospitales 2025, amb coordenades BTN o CartoCiudad.
- `areas.json`: parcel·les disponibles del WFS INSPIRE de la Dirección General del Catastro.
- `sources/`: CSV original del Ministeri i punts hospitalaris extrets de BTN.

Fonts: Ministerio de Sanidad, IGN-CNIG (BTN i CartoCiudad) i Dirección General del Catastro. Les parcel·les estatals no cobreixen País Basc ni Navarra; en aquests casos es conserva el pin.

Actualització:

```sh
npm run build:hospitals -- --cnh data/hospitals/sources/cnh-2025.csv
```
