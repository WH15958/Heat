"""Pure collection geometry shared by planning, control and sample records."""


def collection_capacity(rotation):
    return sum(rotation.ring_counts) if rotation.collection_axis == "rotation" else rotation.bottle_count


def bottle_location(rotation, bottle):
    if type(bottle) is not int or not 1 <= bottle <= collection_capacity(rotation):
        raise ValueError("瓶号超出接样容量，禁止循环使用产物瓶")
    if rotation.collection_axis == "legacy":
        return dict(bottle_number=bottle, rotation_offset=(bottle - 1) * rotation.pulses_per_bottle)
    first = 1
    for ring, count in enumerate(rotation.ring_counts):
        if bottle < first + count:
            local = bottle - first + 1
            offset = ((local - 1) * rotation.counts_per_revolution * 2 + count) // (2 * count)
            return dict(bottle_number=bottle, collection_ring=ring + 1,
                        ring_bottle_number=local, platform_position=rotation.ring_positions[ring],
                        rotation_offset=offset)
        first += count


def collection_plan(config, count):
    rotation = next((c for c in config.turntables if c.device_id == "turntable1" and c.enabled), None)
    if (rotation is None or not rotation.home_enabled or not rotation.position_encoding_verified
            or rotation.collection_axis not in ("legacy", "rotation")):
        raise ValueError("固定接样转盘配置或标定未完成")
    if rotation.collection_axis == "legacy" and rotation.pulses_per_bottle <= 0:
        raise ValueError("转盘瓶位标定无效")
    capacity = collection_capacity(rotation)
    if capacity < 1 or count > capacity:
        raise ValueError(f"本批共 {count} 组，超过转盘 {capacity} 个瓶位；禁止循环覆盖产物瓶")
    devices = [rotation.to_dict()]
    if rotation.collection_axis == "rotation":
        platform = next((c for c in config.turntables if c.device_id == rotation.collection_peer and c.enabled), None)
        if (rotation.ring_counts != [28, 20, 16, 8] or len(rotation.ring_positions) != 4
                or rotation.ring_positions[0] != 0 or rotation.counts_per_revolution != 144000
                or any(type(x) is not int for x in rotation.ring_positions)
                or not all(-9_999_999 <= b < a for a, b in zip(rotation.ring_positions, rotation.ring_positions[1:]))
                or rotation.bottle_count != 0
                or platform is None or platform.collection_axis != "radial" or platform.home_enabled
                or platform.bottle_count != 0
                or not platform.position_encoding_verified or platform.collection_peer != rotation.device_id
                or platform.ring_counts != rotation.ring_counts or platform.ring_positions != rotation.ring_positions
                or platform.counts_per_revolution != rotation.counts_per_revolution):
            raise ValueError("接样平台配对配置或标定未完成")
        devices.append(platform.to_dict())
    return dict(device_id=rotation.device_id, capacity=capacity, devices=devices,
                layout="four_ring" if len(devices) == 2 else "legacy",
                bottle_locations=[bottle_location(rotation, i) for i in range(1, count + 1)])
