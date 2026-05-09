# -*- coding: utf-8 -*-
"""
鸣潮「小团快跑」胜率模拟器

当前规则版本：
1. 棋盘共32格，起点第1格，终点第32格。
2. 普通团子顺时针移动：1 -> 2 -> ... -> 32。
3. 布大王逆时针移动：32 -> 31 -> ... -> 1 -> 32。
4. 普通团子行动点数为1~3。
5. 布大王行动点数为1~6。
6. 每回合行动顺序随机决定。
7. 布大王第3回合开始加入行动顺序。
8. 西格莉卡技能第2回合开始生成标记。
9. 地图装置支持连锁触发。
10. 输出夺冠率与晋级率。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from random import Random
from collections import Counter


BOARD_SIZE = 32
START_POS = 1
FINISH_POS = 32

NORMAL_DICE_MIN = 1
NORMAL_DICE_MAX = 3

BUWANG_DICE_MIN = 1
BUWANG_DICE_MAX = 6

SIGELIKA_START_ROUND = 2

BOOST_CELLS = {3, 11, 16, 23}
BLOCK_CELLS = {10, 28}
RIFT_CELLS = {6, 20}

NORMAL_NAMES = ["陆赫斯", "西格莉卡", "达妮娅", "绯雪", "卡提西娅", "菲比"]
BUWANG_NAME = "布大王"


@dataclass
class Tuanzi:
    name: str
    pos: int = START_POS
    is_buwang: bool = False

    last_dice: int | None = None

    feixue_buff: bool = False

    kati_triggered: bool = False
    kati_active: bool = False

    has_left_start: bool = False


class Race:
    def __init__(self, rng: Random, max_rounds: int = 300):
        self.rng = rng
        self.max_rounds = max_rounds
        self.round_no = 0

        self.racers = [Tuanzi(name=name) for name in NORMAL_NAMES]

        self.buwang = Tuanzi(
            name=BUWANG_NAME,
            pos=FINISH_POS,
            is_buwang=True,
            has_left_start=True,
        )

        self.buwang_on_board = False

        self.cells: dict[int, list[Tuanzi]] = {
            i: [] for i in range(START_POS, FINISH_POS + 1)
        }

        # 所有普通团子从第1格出发。
        # 第1格初始不计算同格状态，所以第一次从起点行动时不会带走其他团子。
        init_order = self.racers[:]
        self.rng.shuffle(init_order)
        self.cells[START_POS] = init_order

        for racer in self.racers:
            racer.pos = START_POS

    def clamp_normal_pos(self, pos: int) -> int:
        """
        普通团子顺时针前进，到达或超过32时停在32。
        """
        return max(START_POS, min(FINISH_POS, pos))

    def wrap_pos(self, pos: int) -> int:
        """
        环形坐标换算。
        1之前是32，32之后是1。
        """
        return ((pos - 1) % BOARD_SIZE) + 1

    def get_cell(self, pos: int) -> list[Tuanzi]:
        return self.cells.setdefault(pos, [])

    def enforce_buwang_bottom(self, pos: int) -> None:
        """
        布大王锁定同格顺序 n=999。

        本脚本中：
        stack[0] 表示 n=1，即最上方；
        stack[-1] 表示最下方。

        因此布大王永远放在该格最下方。
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
        也就是新进入者同格顺序 n 更小。
        """
        old_stack = self.get_cell(pos)
        self.cells[pos] = group + old_stack

        for x in group:
            x.pos = pos
            if not x.is_buwang and pos != START_POS:
                x.has_left_start = True

        self.enforce_buwang_bottom(pos)

    def move_group_normal_path(self, group: list[Tuanzi], delta: int) -> None:
        """
        普通团子的顺时针移动：
        1 -> 2 -> 3 -> ... -> 32

        普通团子不会越过终点，超过32视为到达32。
        """
        if not group or delta == 0:
            return

        old_pos = group[0].pos
        self.remove_group_from_cell(old_pos, group)

        new_pos = self.clamp_normal_pos(old_pos + delta)
        self.add_group_to_cell(new_pos, group)

    def move_group_buwang_path(self, group: list[Tuanzi], delta: int) -> None:
        """
        布大王的逆时针移动：
        32 -> 31 -> 30 -> ... -> 2 -> 1 -> 32

        注意：
        如果布大王行动时带着普通团子一起移动，
        被带走的普通团子也跟随布大王沿逆时针方向移动。
        """
        if not group or delta == 0:
            return

        old_pos = group[0].pos
        self.remove_group_from_cell(old_pos, group)

        # 布大王“前进”时，格号减少。
        # delta 为正：逆时针前进。
        # delta 为负：被阻遏等效果影响时，反向退回。
        new_pos = self.wrap_pos(old_pos - delta)
        self.add_group_to_cell(new_pos, group)

    def moving_group_for_actor(self, actor: Tuanzi) -> list[Tuanzi]:
        """
        同格移动规则：

        stack[0] 是 n=1，最上方。
        stack[1] 是 n=2。
        依此类推。

        如果行动者位于 stack[i]，
        则 stack[:i+1] 跟随行动者一起移动。

        布大王 n=999，始终位于最下方。
        因此布大王行动时，会带走该格所有普通团子；
        普通团子行动时，不会带走布大王。
        """
        stack = self.get_cell(actor.pos)

        # 起点初始不计算同格状态。
        if (
            not actor.is_buwang
            and actor.pos == START_POS
            and not actor.has_left_start
        ):
            return [actor]

        idx = stack.index(actor)
        return stack[: idx + 1]

    def ranking(self) -> list[Tuanzi]:
        """
        普通团子排名：
        1. 位置越靠近终点，排名越高。
        2. 同格时，同格顺序 n 越小，排名越高。
        3. 布大王不参与普通团子排名。
        """
        result: list[Tuanzi] = []

        for pos in range(FINISH_POS, START_POS - 1, -1):
            for x in self.get_cell(pos):
                if not x.is_buwang:
                    result.append(x)

        return result

    def action_order(self, participants: list[Tuanzi]) -> list[Tuanzi]:
        """
        每回合行动顺序随机决定。
        """
        order = participants[:]
        self.rng.shuffle(order)
        return order

    def sigelika_targets(self) -> set[str]:
        """
        西格莉卡：
        从第2回合开始，标记排名紧邻自身且更高的至多两个团子。

        被标记团子本回合移动距离 -1，最低为1。
        """
        rank = self.ranking()
        sigelika = next(x for x in self.racers if x.name == "西格莉卡")

        idx = rank.index(sigelika)
        higher = rank[max(0, idx - 2): idx]

        return {x.name for x in higher}

    def actor_steps(self, actor: Tuanzi, round_debuff: set[str]) -> int:
        """
        计算本次行动点数。

        普通团子：
        行动点数 1~3。

        布大王：
        行动点数 1~6。
        方向不在这里处理，而是在 move_group_buwang_path 中处理。
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

        # 西格莉卡减速，最低移动距离为1。
        if actor.name in round_debuff:
            steps = max(1, steps - 1)

        return steps

    def resolve_devices_chain(
        self,
        group: list[Tuanzi],
        use_buwang_path: bool,
    ) -> None:
        """
        地图装置连锁触发。

        推进装置：
        第3、11、16、23格。
        普通效果：沿当前行动方向前进1格。
        如果移动组中包含陆赫斯，则额外前进3格。

        阻遏装置：
        第10、28格。
        普通效果：沿当前行动方向后退1格。
        如果移动组中包含陆赫斯，则额外后退1格。

        时空裂隙：
        第6、20格。
        随机重排该格普通团子的同格顺序。
        布大王不参与随机重排，仍在最下方。

        use_buwang_path=True：
        表示当前是布大王行动，机关位移也按布大王逆时针方向处理。
        """
        guard = 0

        while group:
            guard += 1

            if guard > 50:
                # 防止未来改地图后出现无限循环。
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
                self.move_group_buwang_path(group, delta)
            else:
                self.move_group_normal_path(group, delta)

    def apply_rift(self, pos: int) -> None:
        """
        时空裂隙：
        随机改变该格普通团子的同格顺序。
        布大王仍然固定为 n=999，保持最下方。
        """
        stack = self.get_cell(pos)

        normals = [x for x in stack if not x.is_buwang]
        buwangs = [x for x in stack if x.is_buwang]

        self.rng.shuffle(normals)
        self.cells[pos] = normals + buwangs

    def check_feixue_meets_buwang(self) -> None:
        """
        绯雪与布大王相遇后，获得持续增益：
        之后绯雪每次自身行动额外前进1格。
        """
        if not self.buwang_on_board:
            return

        feixue = next(x for x in self.racers if x.name == "绯雪")

        if feixue.pos == self.buwang.pos:
            feixue.feixue_buff = True

    def check_kati_after_own_move(self, actor: Tuanzi) -> None:
        """
        卡提西娅：
        每场比赛最多触发1次。
        自身移动结束后若处于最后一名，
        本场剩余回合每次自身行动都有60%概率额外前进2格。
        """
        if actor.name != "卡提西娅":
            return

        if actor.kati_triggered:
            return

        rank = self.ranking()

        if rank and rank[-1].name == "卡提西娅":
            actor.kati_triggered = True
            actor.kati_active = True

    def finishers(self) -> list[Tuanzi]:
        """
        终点格中的普通团子。
        终点格内顺序就是同格顺序 n 从小到大。
        """
        return [x for x in self.get_cell(FINISH_POS) if not x.is_buwang]

    def activate_buwang_if_needed(self) -> None:
        """
        第3回合开始，布大王加入行动顺序。
        """
        if self.round_no >= 3 and not self.buwang_on_board:
            self.buwang_on_board = True
            self.add_group_to_cell(FINISH_POS, [self.buwang])

    def reset_buwang_if_needed(self) -> None:
        """
        整轮行动结束后：
        如果布大王不处于同格状态，则传送回终点。
        """
        if not self.buwang_on_board:
            return

        stack = self.get_cell(self.buwang.pos)

        # 所在格只有布大王自己，说明不处于同格状态。
        if len(stack) == 1 and stack[0].is_buwang:
            self.remove_group_from_cell(self.buwang.pos, [self.buwang])
            self.add_group_to_cell(FINISH_POS, [self.buwang])

    def run(self) -> tuple[list[Tuanzi], list[Tuanzi], int]:
        while self.round_no < self.max_rounds:
            self.round_no += 1

            self.activate_buwang_if_needed()

            participants = self.racers[:]

            if self.round_no >= 3:
                participants.append(self.buwang)

            order = self.action_order(participants)

            # 西格莉卡第1回合不生成标记，第2回合开始生成。
            if self.round_no >= SIGELIKA_START_ROUND:
                round_debuff = self.sigelika_targets()
            else:
                round_debuff = set()

            for actor in order:
                if self.finishers():
                    break

                steps = self.actor_steps(actor, round_debuff)
                group = self.moving_group_for_actor(actor)

                if actor.is_buwang:
                    # 布大王逆时针行动。
                    self.move_group_buwang_path(group, steps)
                    self.resolve_devices_chain(group, use_buwang_path=True)
                else:
                    # 普通团子顺时针行动。
                    self.move_group_normal_path(group, steps)
                    self.resolve_devices_chain(group, use_buwang_path=False)

                self.check_feixue_meets_buwang()
                self.check_kati_after_own_move(actor)

                if self.finishers():
                    return self.finishers(), self.ranking(), self.round_no

            if self.round_no >= 3:
                self.reset_buwang_if_needed()
                self.check_feixue_meets_buwang()

        return self.finishers(), self.ranking(), self.round_no


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
            # 理论兜底：如果超过最大回合仍无人到达终点，则按当前排名第一计冠军。
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