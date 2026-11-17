-- A-owned tables, matching server_interface.md section 5.2.
-- Run before the matching/event schema, whose FKs reference these tables.
CREATE TABLE IF NOT EXISTS zone (
    zone_id TEXT PRIMARY KEY, floor TEXT NOT NULL, name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS camera (
    camera_id TEXT PRIMARY KEY,
    zone_id TEXT NOT NULL REFERENCES zone(zone_id), description TEXT
);
CREATE TABLE IF NOT EXISTS map_node (
    node_id TEXT PRIMARY KEY, floor TEXT NOT NULL,
    x DOUBLE PRECISION NOT NULL, y DOUBLE PRECISION NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('entrance','kiosk','junction','slot_front','elevator'))
);
CREATE TABLE IF NOT EXISTS parking_slot (
    slot_id TEXT PRIMARY KEY, zone_id TEXT NOT NULL REFERENCES zone(zone_id),
    camera_id TEXT NOT NULL REFERENCES camera(camera_id), name TEXT NOT NULL,
    roi JSONB, node_id TEXT NOT NULL REFERENCES map_node(node_id)
);
-- Web-map geometry for the proposed GET /map response; distinct from camera ROI.
ALTER TABLE parking_slot ADD COLUMN IF NOT EXISTS polygon JSONB;
CREATE TABLE IF NOT EXISTS map_edge (
    from_node TEXT NOT NULL REFERENCES map_node(node_id),
    to_node TEXT NOT NULL REFERENCES map_node(node_id),
    length_m DOUBLE PRECISION NOT NULL CHECK (length_m > 0),
    PRIMARY KEY (from_node, to_node), CHECK (from_node <> to_node)
);
CREATE TABLE IF NOT EXISTS qr_location (
    location_id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES map_node(node_id),
    floor TEXT NOT NULL, name TEXT NOT NULL
);
