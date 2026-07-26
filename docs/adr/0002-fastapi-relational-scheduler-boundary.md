# Backend FastAPI con frontera de planificación

Pinendar usa un frontend JavaScript sin compilación y un backend FastAPI con SQLite relacional, empaquetado mediante uv y Docker. La generación se ejecuta como trabajo persistente contra una interfaz `Scheduler`; inicialmente conserva la heurística existente y permitirá incorporar OR-Tools CP-SAT sin cambiar la API ni la interfaz. Se mantiene una sola réplica porque SQLite y el dispatcher local encajan con el uso de una cuenta única.
