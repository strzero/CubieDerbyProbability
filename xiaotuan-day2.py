# -*- coding: utf-8 -*-
"""
鸣潮「小团快跑」下半场胜率模拟器

当前规则版本：
1. 下半场初始位置以上半场结束位置为准。
2. 普通团子顺时针移动：1 -> 2 -> ... -> 32 -> 1 -> ...
3. 布大王逆时针移动：32 -> 31 -> ... -> 1 -> 32。
4. 普通团子行动点数为 1~3。
5. 布大王行动点数为 1~6。
6. 每回合行动顺序随机决定。
7. 布大王第3回合开始加入行动顺序。
8. 西格莉卡技能第2回合开始生成标记。
9. 地图装置支持连锁触发。
10. 下半场以“第二次到达32格”的团子为胜者。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from random import Random
from collections import Counter


BOARD_SIZE = 32
START_POS = 1
FINISH_POS = 32
TARGET_ARRIVALS = 2

NORMAL_DICE_MIN = 1
NORMAL_DICE_MAX = 3

BUWANG_DICE_MIN = 1
BUWANG_DICE_MAX = 6

SIGELIKA_START_ROUND = 2
BUWANG_START_ROUND = 3

BOOST_CELLS = {3, 11, 16, 23}
BLOCK_CELLS = {10, 28}
RIFT_CELLS = {6, 20}

NORMAL_NAMES = ["陆赫斯", "西格莉卡", "达妮娅", "绯雪", "卡提西娅", "菲比"]
BUWANG_NAME = "布大王"


# 下半场初始棋盘。
# 列表顺序表示“从上到下”的同格顺序。
INITIAL_STACKS = {
    32: ["达妮娅"],
    31: ["菲比", "西格莉卡"],
    30: ["绯雪", "陆赫斯"],
    29: ["卡提西娅"],
}


# 下半场“到达32格”计数。
# 达妮娅当前已经在32格，因此视为已经到达过1次。
# 其他团子尚未到达本圈终点，计为0。
INITIAL_ARRIVALS = {name: 0 for name in NORMAL_NAMES}
INITIAL_ARRIVALS["达妮娅"] = 1


# 若下半场第一回合也有固定行动顺序，可以在这里填入列表。
# 保持 None 时，第一回合也随机。
FIRST_ROUND_ORDER = None
# FIRST_ROUND_ORDER = ["卡提西娅", "陆赫斯", "绯雪", "西格莉卡", "菲比", "达妮娅"]


# 若上半场遗留技能状态已知，可以在这里修改。
INITIAL_DANIYA_LAST_DICE = None
INITIAL_FEIXUE_BUFF = False
INITIAL_KATI_TRIGGERED = False
INITIAL_KATI_ACTIVE = False


@dataclass
class Tuanzi:
    name: str
    pos: int = START_POS
    is_buwang: bool = False

    last_dice: int | None = None

    feixue_buff: bool = False

    kati_triggered: bool = False
    kati_active: bool = False

    has_left_start: bool = True


class Race:
    def __init__(self, rng: Random, max_rounds: int = 500):
        self.rng = rng
        self.max_rounds = max_rounds
        self.round_no = 0
        self.race_over = False

        self.racers = [Tuanzi(name=name) for name in NORMAL_NAMES]
        self.name_to_racer = {x.name: x for x in self.racers}

        self.name_to_racer["达妮娅"].last_dice = INITIAL_DANIYA_LAST_DICE
        self.name_to_racer["绯雪"].feixue_buff = INITIAL_FEIXUE_BUFF
        self.name_to_racer["卡提西娅"].kati_triggered = INITIAL_KATI_TRIGGERED
        self.name_to_racer["卡提西娅"].kati_active = INITIAL_KATI_ACTIVE

        self.buwang = Tuanzi(
            name=BUWANG_NAME,
            pos=FINISH_POS,
            is_buwang=True,
            has_left_start=True,
        )
        self.buwang_on_board = False

        self.arrivals = dict(INITIAL_ARRIVALS)

        self.cells: dict[int, list[Tuanzi]] = {
            i: [] for i in range(START_POS, FINISH_POS + 1)
        }

        self.init_board_from_half_time()

    def init_board_from_half_time(self) -> None:
        for pos, names in INITIAL_STACKS.items():
            stack = []
            for name in names:
                racer = self.name_to_racer[name]
                racer.pos = pos
                racer.has_left_start = True
                stack.append(racer)
            self.cells[pos] = stack

    def wrap_pos(self, pos: int) -> int:
        return ((pos - 1) % BOARD_SIZE) + 1

    def get_cell(self, pos: int) -> list[Tuanzi]:
        return self.cells.setdefault(pos, [])

    def enforce_buwang_bottom(self, pos: int) -> None:
        """
        布大王锁定同格顺序 n=999。
        stack[0] 是最上方，stack[-1] 是最下方。
        """
        stack = self.get_cell(pos)
        normals = [x for x in stack if not x.is_buwang]
        buwangs = [x for x in stack if x.is_buwang]
        self.cells[pos] = normals + buwangs

    def remove_group_from_cell(self, pos: int, group: list[Tuanzi]) -> None:
        group_ids = {id(x) for x in group}
        self.cells[pos] = [
            x for x in self.get_cell(pos)
            if id(x) not in group_ids
        ]

    def add_group_to_cell(self, pos: int, group: list[Tuanzi]) -> None:
        """
        新进入该格的团子放在原有团子上方。
        """
        old_stack = self.get_cell(pos)
        self.cells[pos] = group + old_stack

        for x in group:
            x.pos = pos
            if not x.is_buwang:
                x.has_left_start = True

        self.enforce_buwang_bottom(pos)

    def record_arrival_if_needed(self, pos: int, group: list[Tuanzi]) -> bool:
        """
        普通团子进入32格时，到达次数+1。
        达到第二次到达32格时，本场结束。
        """
        if pos != FINISH_POS:
            return False

        has_winner = False

        for x in group:
            if x.is_buwang:
                continue

            self.arrivals[x.name] += 1

            if self.arrivals[x.name] >= TARGET_ARRIVALS:
                has_winner = True

        return has_winner

    def move_group_normal_path(self, group: list[Tuanzi], delta: int) -> bool:
        """
        普通团子顺时针移动。
        delta > 0 表示前进，delta < 0 表示后退。
        """
        return self.move_group_stepwise(group, delta=delta, path="normal")

    def move_group_buwang_path(self, group: list[Tuanzi], delta: int) -> bool:
        """
        布大王逆时针移动。
        delta > 0 表示布大王前进，格号减少。
        """
        return self.move_group_stepwise(group, delta=delta, path="buwang")

    def move_group_stepwise(self, group: list[Tuanzi], delta: int, path: str) -> bool:
        """
        逐格移动。
        这样可以统计移动过程中是否经过32格。
        """
        if not group or delta == 0:
            return False

        old_pos = group[0].pos
        self.remove_group_from_cell(old_pos, group)

        current = old_pos
        step_count = abs(delta)
        sign = 1 if delta > 0 else -1

        for _ in range(step_count):
            if path == "normal":
                current = self.wrap_pos(current + sign)
            elif path == "buwang":
                current = self.wrap_pos(current - sign)
            else:
                raise ValueError(f"未知路径类型：{path}")

            if self.record_arrival_if_needed(current, group):
                self.add_group_to_cell(current, group)
                self.race_over = True
                return True

        self.add_group_to_cell(current, group)
        return False

    def moving_group_for_actor(self, actor: Tuanzi) -> list[Tuanzi]:
        """
        同格移动规则：
        行动团子及其上方团子一起行动。
        """
        stack = self.get_cell(actor.pos)
        idx = stack.index(actor)
        return stack[: idx + 1]

    def ranking(self) -> list[Tuanzi]:
        """
        下半场排名：
        1. 到达32格次数更多者更靠前。
        2. 次数相同，当前位置越接近32越靠前。
        3. 同格时，同格顺序越靠上越靠前。
        """
        entries = []

        for pos in range(START_POS, FINISH_POS + 1):
            for stack_index, x in enumerate(self.get_cell(pos)):
                if x.is_buwang:
                    continue
                entries.append((x, self.arrivals[x.name], pos, stack_index))

        entries.sort(key=lambda item: (-item[1], -item[2], item[3]))

        return [x for x, _arrivals, _pos, _stack_index in entries]

    def action_order(self, participants: list[Tuanzi]) -> list[Tuanzi]:
        """
        默认每回合行动顺序随机。
        若 FIRST_ROUND_ORDER 不为 None，则第一回合使用固定顺序。
        """
        if self.round_no == 1 and FIRST_ROUND_ORDER:
            name_to_actor = {x.name: x for x in participants}

            fixed = [
                name_to_actor[name]
                for name in FIRST_ROUND_ORDER
                if name in name_to_actor
            ]

            remaining = [
                x for x in participants
                if x.name not in FIRST_ROUND_ORDER
            ]

            self.rng.shuffle(remaining)
            return fixed + remaining

        order = participants[:]
        self.rng.shuffle(order)
        return order

    def sigelika_targets(self) -> set[str]:
        """
        西格莉卡：
        第2回合开始，标记排名紧邻自身且更高的至多两个团子。
        """
        rank = self.ranking()
        sigelika = self.name_to_racer["西格莉卡"]

        idx = rank.index(sigelika)
        higher = rank[max(0, idx - 2): idx]

        return {x.name for x in higher}

    def actor_steps(self, actor: Tuanzi, round_debuff: set[str]) -> int:
        """
        计算本次行动点数。
        普通团子：1~3
        布大王：1~6
        """
        if actor.is_buwang:
            return self.rng.randint(BUWANG_DICE_MIN, BUWANG_DICE_MAX)

        dice = self.rng.randint(NORMAL_DICE_MIN, NORMAL_DICE_MAX)
        steps = dice

        if actor.name == "达妮娅":
            if actor.last_dice is not None and actor.last_dice == dice:
                steps += 2
            actor.last_dice = dice

        elif actor.name == "绯雪":
            if actor.feixue_buff:
                steps += 1

        elif actor.name == "卡提西娅":
            if actor.kati_active and self.rng.random() < 0.60:
                steps += 2

        elif actor.name == "菲比":
            if self.rng.random() < 0.50:
                steps += 1

        if actor.name in round_debuff:
            steps = max(1, steps - 1)

        return steps

    def resolve_devices_chain(self, group: list[Tuanzi], use_buwang_path: bool) -> bool:
        """
        地图装置连锁触发。

        推进装置：沿当前行动方向前进1格。
        阻遏装置：沿当前行动方向后退1格。
        陆赫斯在推进装置额外前进3格，在阻遏装置额外后退1格。
        时空裂隙随机重排普通团子同格顺序。
        """
        guard = 0

        while group and not self.race_over:
            guard += 1

            if guard > 50:
                break

            pos = group[0].pos

            if pos in RIFT_CELLS:
                self.apply_rift(pos)
                break

            delta = 0

            if pos in BOOST_CELLS:
                delta = 1
                if any(x.name == "陆赫斯" for x in group):
                    delta += 3

            elif pos in BLOCK_CELLS:
                delta = -1
                if any(x.name == "陆赫斯" for x in group):
                    delta -= 1

            if delta == 0:
                break

            if use_buwang_path:
                if self.move_group_buwang_path(group, delta):
                    return True
            else:
                if self.move_group_normal_path(group, delta):
                    return True

        return False

    def apply_rift(self, pos: int) -> None:
        """
        时空裂隙：
        随机改变该格普通团子的同格顺序。
        布大王不参与随机重排，仍在最下方。
        """
        stack = self.get_cell(pos)

        normals = [x for x in stack if not x.is_buwang]
        buwangs = [x for x in stack if x.is_buwang]

        self.rng.shuffle(normals)
        self.cells[pos] = normals + buwangs

    def check_feixue_meets_buwang(self) -> None:
        """
        绯雪与布大王相遇后，获得持续增益。
        """
        if not self.buwang_on_board:
            return

        feixue = self.name_to_racer["绯雪"]

        if feixue.pos == self.buwang.pos:
            feixue.feixue_buff = True

    def check_kati_after_own_move(self, actor: Tuanzi) -> None:
        """
        卡提西娅：
        自身移动结束后若处于最后一名，则触发后续60%概率额外前进2格。
        """
        if actor.name != "卡提西娅":
            return

        if actor.kati_triggered:
            return

        rank = self.ranking()

        if rank and rank[-1].name == "卡提西娅":
            actor.kati_triggered = True
            actor.kati_active = True

    def eligible_finishers(self) -> list[Tuanzi]:
        """
        已经第二次到达32格的普通团子。
        终点格内仍按同格顺序排列。
        """
        return [
            x for x in self.get_cell(FINISH_POS)
            if not x.is_buwang and self.arrivals[x.name] >= TARGET_ARRIVALS
        ]

    def activate_buwang_if_needed(self) -> None:
        """
        第3回合开始，布大王加入行动顺序。
        """
        if self.round_no >= BUWANG_START_ROUND and not self.buwang_on_board:
            self.buwang_on_board = True
            self.add_group_to_cell(FINISH_POS, [self.buwang])

    def reset_buwang_if_needed(self) -> None:
        """
        整轮结束后：
        如果布大王不处于同格状态，则传送回终点。
        """
        if not self.buwang_on_board:
            return

        stack = self.get_cell(self.buwang.pos)

        if len(stack) == 1 and stack[0].is_buwang:
            self.remove_group_from_cell(self.buwang.pos, [self.buwang])
            self.add_group_to_cell(FINISH_POS, [self.buwang])

    def run(self) -> tuple[list[Tuanzi], list[Tuanzi], int]:
        while self.round_no < self.max_rounds:
            self.round_no += 1

            self.activate_buwang_if_needed()

            participants = self.racers[:]

            if self.round_no >= BUWANG_START_ROUND:
                participants.append(self.buwang)

            order = self.action_order(participants)

            if self.round_no >= SIGELIKA_START_ROUND:
                round_debuff = self.sigelika_targets()
            else:
                round_debuff = set()

            for actor in order:
                if self.race_over:
                    break

                steps = self.actor_steps(actor, round_debuff)
                group = self.moving_group_for_actor(actor)

                if actor.is_buwang:
                    won = self.move_group_buwang_path(group, steps)
                    if not won:
                        won = self.resolve_devices_chain(group, use_buwang_path=True)
                else:
                    won = self.move_group_normal_path(group, steps)
                    if not won:
                        won = self.resolve_devices_chain(group, use_buwang_path=False)

                self.check_feixue_meets_buwang()
                self.check_kati_after_own_move(actor)

                if won or self.eligible_finishers():
                    self.race_over = True
                    return self.eligible_finishers(), self.ranking(), self.round_no

            if self.round_no >= BUWANG_START_ROUND:
                self.reset_buwang_if_needed()
                self.check_feixue_meets_buwang()

        return self.eligible_finishers(), self.ranking(), self.round_no


def simulate(n: int, seed: int) -> None:
    rng = Random(seed)

    champion_count = Counter()
    advance_count = Counter()
    round_count = Counter()

    for _ in range(n):
        race = Race(rng=rng)
        finishers, final_ranking, round_no = race.run()

        if finishers:
            champion_count[finishers[0].name] += 1
        else:
            champion_count[final_ranking[0].name] += 1

        for racer in final_ranking[:4]:
            advance_count[racer.name] += 1

        round_count[round_no] += 1

    print(f"模拟次数：{n}")
    print(f"随机种子：{seed}")
    print()

    print("=== 夺冠率 ===")
    for name in NORMAL_NAMES:
        rate = champion_count[name] / n * 100
        print(f"{name:<5} {rate:6.2f}%")

    print()
    print("=== 晋级率：比赛结束时总排名前4 ===")
    for name in NORMAL_NAMES:
        rate = advance_count[name] / n * 100
        print(f"{name:<5} {rate:6.2f}%")

    print()
    avg_round = sum(k * v for k, v in round_count.items()) / n
    print(f"平均结束回合数：{avg_round:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100000, help="模拟次数")
    parser.add_argument("--seed", type=int, default=20260509, help="随机种子")

    args = parser.parse_args()

    simulate(args.n, args.seed)


if __name__ == "__main__":
    main()