-- 원본: psubin05/SPASIBA subin_server 브랜치 db/map_seed.sql (커밋 d36f941, 수빈 담당). 여기서 고치지 말고 원본이 바뀌면 다시 복사한다.
-- 용도: 로컬 Docker DB에 샘플 지도(구역 2, 카메라 2, 칸 8, QR 1)를 넣는다. README '로컬 통합 실행' 참고.
-- Generated from validated map JSON; existing rows are updated, never deleted.
BEGIN;
SET LOCAL standard_conforming_strings = on;
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

INSERT INTO zone (zone_id, floor, name) VALUES ('B2-A', 'B2', 'A') ON CONFLICT (zone_id) DO UPDATE SET floor = EXCLUDED.floor, name = EXCLUDED.name;
INSERT INTO zone (zone_id, floor, name) VALUES ('B2-B', 'B2', 'B') ON CONFLICT (zone_id) DO UPDATE SET floor = EXCLUDED.floor, name = EXCLUDED.name;
INSERT INTO camera (camera_id, zone_id, description) VALUES ('CAM-B2-A-01', 'B2-A', 'Sample camera') ON CONFLICT (camera_id) DO UPDATE SET zone_id = EXCLUDED.zone_id, description = EXCLUDED.description;
INSERT INTO camera (camera_id, zone_id, description) VALUES ('CAM-B2-B-01', 'B2-B', 'Sample camera') ON CONFLICT (camera_id) DO UPDATE SET zone_id = EXCLUDED.zone_id, description = EXCLUDED.description;
INSERT INTO map_node (node_id, floor, x, y, type) VALUES ('ENT1', 'B2', 0, 3, 'entrance') ON CONFLICT (node_id) DO UPDATE SET floor = EXCLUDED.floor, x = EXCLUDED.x, y = EXCLUDED.y, type = EXCLUDED.type;
INSERT INTO map_node (node_id, floor, x, y, type) VALUES ('J1', 'B2', 3, 3, 'junction') ON CONFLICT (node_id) DO UPDATE SET floor = EXCLUDED.floor, x = EXCLUDED.x, y = EXCLUDED.y, type = EXCLUDED.type;
INSERT INTO map_node (node_id, floor, x, y, type) VALUES ('J2', 'B2', 7, 3, 'junction') ON CONFLICT (node_id) DO UPDATE SET floor = EXCLUDED.floor, x = EXCLUDED.x, y = EXCLUDED.y, type = EXCLUDED.type;
INSERT INTO map_node (node_id, floor, x, y, type) VALUES ('J3', 'B2', 11, 3, 'junction') ON CONFLICT (node_id) DO UPDATE SET floor = EXCLUDED.floor, x = EXCLUDED.x, y = EXCLUDED.y, type = EXCLUDED.type;
INSERT INTO map_node (node_id, floor, x, y, type) VALUES ('J4', 'B2', 15, 3, 'junction') ON CONFLICT (node_id) DO UPDATE SET floor = EXCLUDED.floor, x = EXCLUDED.x, y = EXCLUDED.y, type = EXCLUDED.type;
INSERT INTO map_node (node_id, floor, x, y, type) VALUES ('J5', 'B2', 19, 3, 'junction') ON CONFLICT (node_id) DO UPDATE SET floor = EXCLUDED.floor, x = EXCLUDED.x, y = EXCLUDED.y, type = EXCLUDED.type;
INSERT INTO map_node (node_id, floor, x, y, type) VALUES ('N-A01', 'B2', 7, 2, 'slot_front') ON CONFLICT (node_id) DO UPDATE SET floor = EXCLUDED.floor, x = EXCLUDED.x, y = EXCLUDED.y, type = EXCLUDED.type;
INSERT INTO map_node (node_id, floor, x, y, type) VALUES ('N-A02', 'B2', 11, 2, 'slot_front') ON CONFLICT (node_id) DO UPDATE SET floor = EXCLUDED.floor, x = EXCLUDED.x, y = EXCLUDED.y, type = EXCLUDED.type;
INSERT INTO map_node (node_id, floor, x, y, type) VALUES ('N-A03', 'B2', 15, 2, 'slot_front') ON CONFLICT (node_id) DO UPDATE SET floor = EXCLUDED.floor, x = EXCLUDED.x, y = EXCLUDED.y, type = EXCLUDED.type;
INSERT INTO map_node (node_id, floor, x, y, type) VALUES ('N-A04', 'B2', 19, 2, 'slot_front') ON CONFLICT (node_id) DO UPDATE SET floor = EXCLUDED.floor, x = EXCLUDED.x, y = EXCLUDED.y, type = EXCLUDED.type;
INSERT INTO map_node (node_id, floor, x, y, type) VALUES ('N-B01', 'B2', 7, 4, 'slot_front') ON CONFLICT (node_id) DO UPDATE SET floor = EXCLUDED.floor, x = EXCLUDED.x, y = EXCLUDED.y, type = EXCLUDED.type;
INSERT INTO map_node (node_id, floor, x, y, type) VALUES ('N-B02', 'B2', 11, 4, 'slot_front') ON CONFLICT (node_id) DO UPDATE SET floor = EXCLUDED.floor, x = EXCLUDED.x, y = EXCLUDED.y, type = EXCLUDED.type;
INSERT INTO map_node (node_id, floor, x, y, type) VALUES ('N-B03', 'B2', 15, 4, 'slot_front') ON CONFLICT (node_id) DO UPDATE SET floor = EXCLUDED.floor, x = EXCLUDED.x, y = EXCLUDED.y, type = EXCLUDED.type;
INSERT INTO map_node (node_id, floor, x, y, type) VALUES ('N-B04', 'B2', 19, 4, 'slot_front') ON CONFLICT (node_id) DO UPDATE SET floor = EXCLUDED.floor, x = EXCLUDED.x, y = EXCLUDED.y, type = EXCLUDED.type;
INSERT INTO parking_slot (slot_id, zone_id, camera_id, name, roi, node_id, polygon) VALUES ('B2-A-01', 'B2-A', 'CAM-B2-A-01', 'A-01', NULL, 'N-A01', '[[5.75, -0.6], [8.25, -0.6], [8.25, 1.4], [5.75, 1.4]]'::jsonb) ON CONFLICT (slot_id) DO UPDATE SET zone_id = EXCLUDED.zone_id, camera_id = EXCLUDED.camera_id, name = EXCLUDED.name, roi = EXCLUDED.roi, node_id = EXCLUDED.node_id, polygon = EXCLUDED.polygon;
INSERT INTO parking_slot (slot_id, zone_id, camera_id, name, roi, node_id, polygon) VALUES ('B2-A-02', 'B2-A', 'CAM-B2-A-01', 'A-02', NULL, 'N-A02', '[[9.75, -0.6], [12.25, -0.6], [12.25, 1.4], [9.75, 1.4]]'::jsonb) ON CONFLICT (slot_id) DO UPDATE SET zone_id = EXCLUDED.zone_id, camera_id = EXCLUDED.camera_id, name = EXCLUDED.name, roi = EXCLUDED.roi, node_id = EXCLUDED.node_id, polygon = EXCLUDED.polygon;
INSERT INTO parking_slot (slot_id, zone_id, camera_id, name, roi, node_id, polygon) VALUES ('B2-A-03', 'B2-A', 'CAM-B2-A-01', 'A-03', NULL, 'N-A03', '[[13.75, -0.6], [16.25, -0.6], [16.25, 1.4], [13.75, 1.4]]'::jsonb) ON CONFLICT (slot_id) DO UPDATE SET zone_id = EXCLUDED.zone_id, camera_id = EXCLUDED.camera_id, name = EXCLUDED.name, roi = EXCLUDED.roi, node_id = EXCLUDED.node_id, polygon = EXCLUDED.polygon;
INSERT INTO parking_slot (slot_id, zone_id, camera_id, name, roi, node_id, polygon) VALUES ('B2-A-04', 'B2-A', 'CAM-B2-A-01', 'A-04', NULL, 'N-A04', '[[17.75, -0.6], [20.25, -0.6], [20.25, 1.4], [17.75, 1.4]]'::jsonb) ON CONFLICT (slot_id) DO UPDATE SET zone_id = EXCLUDED.zone_id, camera_id = EXCLUDED.camera_id, name = EXCLUDED.name, roi = EXCLUDED.roi, node_id = EXCLUDED.node_id, polygon = EXCLUDED.polygon;
INSERT INTO parking_slot (slot_id, zone_id, camera_id, name, roi, node_id, polygon) VALUES ('B2-B-01', 'B2-B', 'CAM-B2-B-01', 'B-01', NULL, 'N-B01', '[[5.75, 4.6], [8.25, 4.6], [8.25, 6.6], [5.75, 6.6]]'::jsonb) ON CONFLICT (slot_id) DO UPDATE SET zone_id = EXCLUDED.zone_id, camera_id = EXCLUDED.camera_id, name = EXCLUDED.name, roi = EXCLUDED.roi, node_id = EXCLUDED.node_id, polygon = EXCLUDED.polygon;
INSERT INTO parking_slot (slot_id, zone_id, camera_id, name, roi, node_id, polygon) VALUES ('B2-B-02', 'B2-B', 'CAM-B2-B-01', 'B-02', NULL, 'N-B02', '[[9.75, 4.6], [12.25, 4.6], [12.25, 6.6], [9.75, 6.6]]'::jsonb) ON CONFLICT (slot_id) DO UPDATE SET zone_id = EXCLUDED.zone_id, camera_id = EXCLUDED.camera_id, name = EXCLUDED.name, roi = EXCLUDED.roi, node_id = EXCLUDED.node_id, polygon = EXCLUDED.polygon;
INSERT INTO parking_slot (slot_id, zone_id, camera_id, name, roi, node_id, polygon) VALUES ('B2-B-03', 'B2-B', 'CAM-B2-B-01', 'B-03', NULL, 'N-B03', '[[13.75, 4.6], [16.25, 4.6], [16.25, 6.6], [13.75, 6.6]]'::jsonb) ON CONFLICT (slot_id) DO UPDATE SET zone_id = EXCLUDED.zone_id, camera_id = EXCLUDED.camera_id, name = EXCLUDED.name, roi = EXCLUDED.roi, node_id = EXCLUDED.node_id, polygon = EXCLUDED.polygon;
INSERT INTO parking_slot (slot_id, zone_id, camera_id, name, roi, node_id, polygon) VALUES ('B2-B-04', 'B2-B', 'CAM-B2-B-01', 'B-04', NULL, 'N-B04', '[[17.75, 4.6], [20.25, 4.6], [20.25, 6.6], [17.75, 6.6]]'::jsonb) ON CONFLICT (slot_id) DO UPDATE SET zone_id = EXCLUDED.zone_id, camera_id = EXCLUDED.camera_id, name = EXCLUDED.name, roi = EXCLUDED.roi, node_id = EXCLUDED.node_id, polygon = EXCLUDED.polygon;
INSERT INTO map_edge (from_node, to_node, length_m) VALUES ('ENT1', 'J1', 3) ON CONFLICT (from_node, to_node) DO UPDATE SET length_m = EXCLUDED.length_m;
INSERT INTO map_edge (from_node, to_node, length_m) VALUES ('J1', 'J2', 4) ON CONFLICT (from_node, to_node) DO UPDATE SET length_m = EXCLUDED.length_m;
INSERT INTO map_edge (from_node, to_node, length_m) VALUES ('J2', 'J3', 4) ON CONFLICT (from_node, to_node) DO UPDATE SET length_m = EXCLUDED.length_m;
INSERT INTO map_edge (from_node, to_node, length_m) VALUES ('J3', 'J4', 4) ON CONFLICT (from_node, to_node) DO UPDATE SET length_m = EXCLUDED.length_m;
INSERT INTO map_edge (from_node, to_node, length_m) VALUES ('J4', 'J5', 4) ON CONFLICT (from_node, to_node) DO UPDATE SET length_m = EXCLUDED.length_m;
INSERT INTO map_edge (from_node, to_node, length_m) VALUES ('J2', 'N-A01', 1) ON CONFLICT (from_node, to_node) DO UPDATE SET length_m = EXCLUDED.length_m;
INSERT INTO map_edge (from_node, to_node, length_m) VALUES ('J3', 'N-A02', 1) ON CONFLICT (from_node, to_node) DO UPDATE SET length_m = EXCLUDED.length_m;
INSERT INTO map_edge (from_node, to_node, length_m) VALUES ('J4', 'N-A03', 1) ON CONFLICT (from_node, to_node) DO UPDATE SET length_m = EXCLUDED.length_m;
INSERT INTO map_edge (from_node, to_node, length_m) VALUES ('J5', 'N-A04', 1) ON CONFLICT (from_node, to_node) DO UPDATE SET length_m = EXCLUDED.length_m;
INSERT INTO map_edge (from_node, to_node, length_m) VALUES ('J2', 'N-B01', 1) ON CONFLICT (from_node, to_node) DO UPDATE SET length_m = EXCLUDED.length_m;
INSERT INTO map_edge (from_node, to_node, length_m) VALUES ('J3', 'N-B02', 1) ON CONFLICT (from_node, to_node) DO UPDATE SET length_m = EXCLUDED.length_m;
INSERT INTO map_edge (from_node, to_node, length_m) VALUES ('J4', 'N-B03', 1) ON CONFLICT (from_node, to_node) DO UPDATE SET length_m = EXCLUDED.length_m;
INSERT INTO map_edge (from_node, to_node, length_m) VALUES ('J5', 'N-B04', 1) ON CONFLICT (from_node, to_node) DO UPDATE SET length_m = EXCLUDED.length_m;
INSERT INTO qr_location (location_id, node_id, floor, name) VALUES ('QR-B2-ENT1', 'ENT1', 'B2', '출입구 A') ON CONFLICT (location_id) DO UPDATE SET node_id = EXCLUDED.node_id, floor = EXCLUDED.floor, name = EXCLUDED.name;
COMMIT;
