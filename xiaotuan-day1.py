# -*- coding: utf-8 -*-
"""
鸣潮「小团快跑」胜率模拟器

输出：
1. 夺冠率：谁成为本场第一名
2. 晋级率：比赛结束时总排名前4的概率

运行示例：
python xiaotuan_sim.py --n 100000 --seed 20260509
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from random import Random
from collections import Counter


BOARD_SIZE = 32
START_POS = 1
FINISH_POS = 32

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

    # 技能状态
    last_dice: int | None = None
    feixue_buff: bool = False
    kati_triggered: bool = False
    kati_active: bool = False

    # 用于处理“第1格出发时不计算同格状态”
    has_left_start: bool = False


class Race:
    def __init__(
        self,
        rng: Random,
        sigelika_mark_from_round: int = 2,
        max_rounds: int = 200,
    ):
        self.rng = rng
        self.round_no = 0
        self.max_rounds = max_rounds

        # 西格莉卡技能默认从第2回合开始生效：
        self.sigelika_mark_from_round = sigelika_mark_from_round

        self.racers = [Tuanzi(name=name) for name in NORMAL_NAMES]
        self.buwang = Tuanzi(
            name=BUWANG_NAME,
            pos=FINISH_POS,
            is_buwang=True,
            has_left_start=True,
        )
        self.buwang_on_board = False

        self.cells = {i: [] for i in range(1, BOARD_SIZE + 1)}

        # 起点多人，但不计算同格状态；这里先随机放置，避免固定顺序影响排名
        init_order = self.racers[:]
        self.rng.shuffle(init_order)
        self.cells[START_POS] = init_order

        for racer in self.racers:
            racer.pos = START_POS

    def clamp(self, pos: int) -> int:
        return max(START_POS, min(FINISH_POS, pos))

    def get_cell(self, pos: int) -> list[Tuanzi]:
        return self.cells.setdefault(pos, [])

    def enforce_buwang_bottom(self, pos: int) -> None:
        """
        布大王锁定同格顺序 n=999。
        本程序用列表表示同格顺序：
        stack[0] = n最小，也就是最上方、排名更靠前；
        stack[-1] = n最大，也就是最下方。
        """
        stack = self.get_cell(pos)
        normals = [x for x in stack if not x.is_buwang]
        buwangs = [x for x in stack if x.is_buwang]
        self.cells[pos] = normals + buwangs

    def remove_group_from_cell(self, pos: int, group: list[Tuanzi]) -> None:
        group_ids = {id(x) for x in group}
        self.cells[pos] = [x for x in self.get_cell(pos) if id(x) not in group_ids]

    def add_group_to_cell(self, pos: int, group: list[Tuanzi]) -> None:
        """
        新落入该格的团子同格顺序更靠前。
        所以移动组整体放到原有团子上方。
        """
        pos = self.clamp(pos)
        old_stack = self.get_cell(pos)

        self.cells[pos] = group + old_stack

        for x in group:
            x.pos = pos
            if not x.is_buwang and pos != START_POS:
                x.has_left_start = True

        self.enforce_buwang_bottom(pos)

    def move_group_by_delta(self, group: list[Tuanzi], delta: int) -> None:
        if not group or delta == 0:
            return

        old_pos = group[0].pos
        self.remove_group_from_cell(old_pos, group)

        new_pos = self.clamp(old_pos + delta)
        self.add_group_to_cell(new_pos, group)

    def moving_group_for_actor(self, actor: Tuanzi) -> list[Tuanzi]:
        """
        同格行动规则：
        行动者处于同格状态时，同格顺序 n <= 行动者 n 的团子一起行动。

        本程序中：
        stack[0] 是 n=1
        stack[1] 是 n=2
        以此类推

        如果 actor 是 stack[i]，则 stack[:i+1] 一起移动。
        """
        stack = self.get_cell(actor.pos)

        # 出发时，第1格普通团子不计算同格状态
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
        总排名：
        1. 离终点越近，排名越高
        2. 同格时，同格顺序 n 越小，排名越高
        3. 布大王不参与普通团子排名
        """
        result = []

        for pos in range(FINISH_POS, START_POS - 1, -1):
            for x in self.get_cell(pos):
                if not x.is_buwang:
                    result.append(x)

        return result

    def action_order(self, participants: list[Tuanzi]) -> list[Tuanzi]:
        """
        每回合重新投骰决定行动顺序。
        点数越大越先行动。
        同点数随机排序。
        """
        temp = participants[:]

        # 先洗牌，再按点数排序，天然实现“同点数随机排序”
        self.rng.shuffle(temp)
        order_rolls = {x.name: self.rng.randint(1, 6) for x in temp}

        temp.sort(key=lambda x: order_rolls[x.name], reverse=True)
        return temp

    def sigelika_targets(self) -> set[str]:
        """
        西格莉卡：
        标记排名紧邻自身且更高的至多两个团子。
        """
        rank = self.ranking()
        sigelika = next(x for x in self.racers if x.name == "西格莉卡")

        idx = rank.index(sigelika)

        # 榜单中位于西格莉卡前方的最近两个
        higher = rank[max(0, idx - 2): idx]
        return {x.name for x in higher}

    def actor_steps(self, actor: Tuanzi, round_debuff: set[str]) -> int:
        """
        计算本次行动的基础移动步数。
        地图装置不在这里处理，而是在移动后连锁处理。
        """
        dice = self.rng.randint(1, 6)

        if actor.is_buwang:
            return -dice

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

        # 西格莉卡减速：本回合少前进1格，但最低为1格
        if actor.name in round_debuff:
            steps = max(1, steps - 1)

        return steps

    def resolve_devices_chain(self, group: list[Tuanzi]) -> None:
        """
        连锁触发地图装置。

        推进装置：
        普通情况 +1
        如果移动组内有陆赫斯，则额外 +3，合计 +4

        阻遏装置：
        普通情况 -1
        如果移动组内有陆赫斯，则额外 -1，合计 -2

        时空裂隙：
        随机改变该格普通团子的堆叠顺序；
        布大王不参与随机重排，并继续锁定在最下方。
        """
        guard = 0

        while group:
            guard += 1
            if guard > 20:
                # 防止未来改地图时出现无限循环
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

            self.move_group_by_delta(group, delta)

    def apply_rift(self, pos: int) -> None:
        """
        时空裂隙：
        随机改变普通团子堆叠顺序。
        布大王不受影响，继续保持 n=999。
        """
        stack = self.get_cell(pos)

        normals = [x for x in stack if not x.is_buwang]
        buwangs = [x for x in stack if x.is_buwang]

        self.rng.shuffle(normals)

        self.cells[pos] = normals + buwangs

    def check_feixue_meets_buwang(self) -> None:
        """
        绯雪与布大王相遇后，之后每次自身行动额外前进1格。
        """
        if not self.buwang_on_board:
            return

        feixue = next(x for x in self.racers if x.name == "绯雪")

        if feixue.pos == self.buwang.pos:
            feixue.feixue_buff = True

    def check_kati_after_own_move(self, actor: Tuanzi) -> None:
        """
        卡提西娅：
        每场最多触发1次。
        自身移动结束后，若处于最后一名，
        本场比赛剩余回合都会有60%概率额外前进2格。
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
        终点格内的顺序就是同格顺序 n 从小到大。
        """
        return [x for x in self.get_cell(FINISH_POS) if not x.is_buwang]

    def reset_buwang_if_needed(self) -> None:
        """
        整轮行动结束后，若布大王不处于同格状态，则传送回终点。
        """
        if not self.buwang_on_board:
            return

        stack = self.get_cell(self.buwang.pos)

        # 所在格只有布大王自己，视为不处于同格状态
        if len(stack) == 1 and stack[0].is_buwang:
            self.remove_group_from_cell(self.buwang.pos, [self.buwang])
            self.add_group_to_cell(FINISH_POS, [self.buwang])

    def activate_buwang_if_needed(self) -> None:
        """
        第3回合开始，布大王从终点加入行动顺序。
        """
        if self.round_no >= 3 and not self.buwang_on_board:
            self.buwang_on_board = True
            self.add_group_to_cell(FINISH_POS, [self.buwang])

    def run(self) -> tuple[list[Tuanzi], list[Tuanzi], int]:
        """
        返回：
        finishers_in_order：终点格获胜团子顺序
        final_ranking：比赛结束时普通团子总排名
        round_no：比赛结束回合
        """
        while self.round_no < self.max_rounds:
            self.round_no += 1
            self.activate_buwang_if_needed()

            participants = self.racers[:]
            if self.round_no >= 3:
                participants.append(self.buwang)

            order = self.action_order(participants)

            if self.round_no >= self.sigelika_mark_from_round:
                round_debuff = self.sigelika_targets()
            else:
                round_debuff = set()

            for actor in order:
                # 如果已经有人到终点，保险退出
                if self.finishers():
                    break

                steps = self.actor_steps(actor, round_debuff)
                group = self.moving_group_for_actor(actor)

                self.move_group_by_delta(group, steps)
                self.resolve_devices_chain(group)

                self.check_feixue_meets_buwang()
                self.check_kati_after_own_move(actor)

                if self.finishers():
                    return self.finishers(), self.ranking(), self.round_no

            if self.round_no >= 3:
                self.reset_buwang_if_needed()
                self.check_feixue_meets_buwang()

        # 理论上很少触发，只作为兜底
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
            # 极端兜底：如果没进终点，就按最终排名第一视为冠军
            champion_count[final_ranking[0].name] += 1

        # 晋级：比赛结束时总排名前4
        for racer in final_ranking[:4]:
            advance_count[racer.name] += 1

        round_count[round_no] += 1

    print(f"模拟次数：{n}")
    print(f"随机种子：{seed}")
    print()

    print("=== 夺冠率 ===")
    for name in NORMAL_NAMES:
        rate = champion_count[name] / n * 100
        print(f"{name:<4}  {rate:6.2f}%")

    print()
    print("=== 晋级率：比赛结束时总排名前4 ===")
    for name in NORMAL_NAMES:
        rate = advance_count[name] / n * 100
        print(f"{name:<4}  {rate:6.2f}%")

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
