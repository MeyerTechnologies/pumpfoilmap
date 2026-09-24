[out:json][timeout:600];
area["ISO3166-1"="DK"][admin_level=2]->.dk;
(
  nwr["man_made"="pier"](area.dk);
  nwr["floating"="yes"](area.dk);
  nwr["leisure"~"^(bathing_place|swimming_area|marina|slipway)$"](area.dk);
  nwr["sport"~"canoe|kayak|rowing|paddle|sup|stand_up_paddle"](area.dk);
  nwr["amenity"="boat_rental"](area.dk);
  nwr["name"~"[Kk]ajak|[Kk]ano|[Rr]oklub|[Rr]o- og|[Rr]oforening|[Vv]interbad|[Ss]øbad|[Hh]avnebad|[Bb]adebro|[Bb]adeanstalt|[Ss]ejlklub|[Ff]lydebro|[Bb]adeklub"](area.dk);
)->.hits;
way.hits; out tags geom;
node.hits; out;
rel.hits; out tags center;
node["place"~"^(city|town|village|suburb|hamlet)$"](area.dk); out;
