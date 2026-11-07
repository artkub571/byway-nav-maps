# Byway Nav map data

Open map data for the [Byway Nav](https://github.com/artkub571) motorcycle
navigation app, built here by GitHub Actions from open sources. The app
downloads these files directly: no GitHub account or sign-in is needed.

This repository holds **only open data and the scripts that build it**. Nothing
personal is kept here.

## What's here

| Data | Where | Built by | Updated |
|---|---|---|---|
| Offline vector map of Great Britain (`gb.pmtiles`, about 1.3 GB) | [Releases](../../releases) (`vector-map-gb-*`), with `manifest.json` (size, SHA-256, parts) | Actions → **Vector map (GB)** | By hand |
| Small vector map sample (Salisbury Plain) | branch `vector-sample` | Vector map (GB) | With the map |
| Twisty roads (`twisty-gb.json.gz`) | branch `twisty-data` | Actions → **Twisty roads (GB)** (`tools/twisty`) | By hand, every few months |
| Soil drainage map (`drainage-gb.bin.gz`) | branch `soil-data` | Actions → **Soil drainage map** (`tools/soil`) | By hand, when the rules change |
| MoD firing times (`firing.json`) | branch `firing-data` | Actions → **MoD firing times** (`tools/firing`) | Daily |

## Licences and credits

- **Vector map, twisty roads, MoD danger areas:** map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright),
  available under the [Open Database Licence (ODbL)](https://opendatacommons.org/licenses/odbl/).
  The vector map is cut from the open [Protomaps](https://protomaps.com) daily build; twisty roads
  are computed from the [Geofabrik](https://download.geofabrik.de) Great Britain extract.
  Anything made from these files must credit OpenStreetMap contributors, and a changed database
  must be shared under the ODbL.
- **Soil drainage map:** contains British Geological Survey materials © UKRI
  (BGS Geology 625k, [Open Government Licence](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/));
  SoilGrids topsoil clay © [ISRIC](https://www.isric.org) ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)).
- **MoD firing times:** from gov.uk firing-notice publications, Crown copyright,
  [Open Government Licence](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
  Notices show when firing is *permitted*, not booked. Always check the range's own notice and the
  red flags or lights on the ground before entering.

## Running the builds

Actions → choose the workflow → **Run workflow**. Each job pushes its result
to its branch (or a release) in this repository using the job's own
`GITHUB_TOKEN`; no other keys are involved.

Script tests (Python 3.12):

```bash
pip install pytest numpy shapely pillow
python -m pytest -q tools/twisty/tests tools/soil/tests tools/firing/tests
```
