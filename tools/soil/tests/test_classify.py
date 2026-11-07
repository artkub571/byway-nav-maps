import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from classify import FAST, MEDIUM, SLOW, UNKNOWN, bedrock_class, pack, superficial_class, unpack, with_clay  # noqa: E402


def test_bedrock_rocks():
    assert bedrock_class("CHALK") == FAST
    assert bedrock_class("LIMESTONE") == FAST
    assert bedrock_class("SANDSTONE AND CONGLOMERATE, INTERBEDDED") == FAST
    assert bedrock_class("CLAY, SILT AND SAND") == SLOW  # London Clay
    assert bedrock_class("MUDSTONE, SILTSTONE AND SANDSTONE") == SLOW  # Culm
    assert bedrock_class("SANDSTONE, SILTSTONE AND MUDSTONE") == MEDIUM
    assert bedrock_class("LIMESTONE AND MUDSTONE, INTERBEDDED") == MEDIUM  # Lias
    assert bedrock_class("GRANITE") == MEDIUM
    assert bedrock_class("", "MILLSTONE GRIT GROUP") == FAST


def test_superficial_deposits():
    assert superficial_class("PEAT") == SLOW
    assert superficial_class("TILL, DEVENSIAN", "DIAMICTON") == SLOW
    assert superficial_class("ALLUVIUM", "CLAY, SILT, SAND AND GRAVEL") == SLOW
    assert superficial_class("CLAY-WITH-FLINTS FORMATION", "CLAY, SILT, SAND AND GRAVEL") == SLOW
    assert superficial_class("RIVER TERRACE DEPOSITS", "SAND AND GRAVEL") == FAST
    assert superficial_class("GLACIOFLUVIAL DEPOSITS, DEVENSIAN", "SAND AND GRAVEL") == FAST
    assert superficial_class("HEAD", "CLAY, SILT, SAND AND GRAVEL") == MEDIUM
    assert superficial_class("", "") == UNKNOWN


def test_clay_only_slows_ground():
    assert with_clay(FAST, 32) == MEDIUM
    assert with_clay(FAST, 20) == FAST
    assert with_clay(MEDIUM, 40) == SLOW
    assert with_clay(SLOW, 5) == SLOW
    assert with_clay(UNKNOWN, 40) == UNKNOWN
    assert with_clay(MEDIUM, None) == MEDIUM


def test_pack_round_trip():
    cells = [0, 1, 2, 3, 3, 2, 1, 0, 1]
    data = pack(cells)
    assert len(data) == 3
    assert data[0] == 0b11_10_01_00
    assert unpack(data, len(cells)) == cells
