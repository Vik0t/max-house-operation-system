from app.config_loader import get_house_config, load_all_configs


def test_two_houses_have_different_topology_and_routing():
    configs = load_all_configs()
    assert {item.house.id for item in configs} == {"demo-house-a", "demo-house-b"}
    house_a = get_house_config("demo-house-a")
    house_b = get_house_config("demo-house-b")
    assert len(house_a.assets) != len(house_b.assets)
    assert house_a.routing["elevator"].destination != house_b.routing["elevator"].destination
    assert house_a.recurrence.count == 3
    assert house_b.recurrence.count == 2

