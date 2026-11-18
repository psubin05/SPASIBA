"""지도 표 6개 (수빈 담당). 우리 쪽은 읽기만 한다.

원본: 수빈의 db/map_schema.sql (subin_server d36f941, 사본은 server/db/map_schema.sql).
이 파일은 우리 표의 FK와 SQLite 테스트를 위해 원본을 **그대로 옮긴 것**이다. 여기서 고치지 말고,
원본이 바뀌면 같이 맞춘다 (tests/test_models.py::test_map_columns_match_subin_sql 이 열 이름을 대조).
운영 PostgreSQL에서는 수빈의 SQL을 먼저 실행하면 create_all이 이 표들은 건너뛴다.
"""
from __future__ import annotations

from sqlalchemy import CheckConstraint, Double, ForeignKey, PrimaryKeyConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, JsonType


class Zone(Base):
    __tablename__ = "zone"
    zone_id: Mapped[str] = mapped_column(Text, primary_key=True)
    floor: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class Camera(Base):
    __tablename__ = "camera"
    camera_id: Mapped[str] = mapped_column(Text, primary_key=True)
    zone_id: Mapped[str] = mapped_column(Text, ForeignKey("zone.zone_id"), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class MapNode(Base):
    __tablename__ = "map_node"
    __table_args__ = (
        CheckConstraint("type IN ('entrance','kiosk','junction','slot_front','elevator')"),
    )
    node_id: Mapped[str] = mapped_column(Text, primary_key=True)
    floor: Mapped[str] = mapped_column(Text, nullable=False)
    x: Mapped[float] = mapped_column(Double, nullable=False)
    y: Mapped[float] = mapped_column(Double, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)


class ParkingSlot(Base):
    __tablename__ = "parking_slot"
    slot_id: Mapped[str] = mapped_column(Text, primary_key=True)
    zone_id: Mapped[str] = mapped_column(Text, ForeignKey("zone.zone_id"), nullable=False)
    camera_id: Mapped[str] = mapped_column(Text, ForeignKey("camera.camera_id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    roi = mapped_column(JsonType)
    node_id: Mapped[str] = mapped_column(Text, ForeignKey("map_node.node_id"), nullable=False)
    polygon = mapped_column(JsonType)  # 웹 지도 경계 (/map 응답용), 카메라 roi와 다른 좌표계


class MapEdge(Base):
    __tablename__ = "map_edge"
    __table_args__ = (
        PrimaryKeyConstraint("from_node", "to_node"),
        CheckConstraint("length_m > 0"),
        CheckConstraint("from_node <> to_node"),
    )
    from_node: Mapped[str] = mapped_column(Text, ForeignKey("map_node.node_id"), nullable=False)
    to_node: Mapped[str] = mapped_column(Text, ForeignKey("map_node.node_id"), nullable=False)
    length_m: Mapped[float] = mapped_column(Double, nullable=False)


class QrLocation(Base):
    __tablename__ = "qr_location"
    location_id: Mapped[str] = mapped_column(Text, primary_key=True)
    node_id: Mapped[str] = mapped_column(Text, ForeignKey("map_node.node_id"), nullable=False)
    floor: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
