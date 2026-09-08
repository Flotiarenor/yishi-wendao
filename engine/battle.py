"""回合制战斗（P2/P3）：纯逻辑状态机，不碰 I/O、不 import cli。

架构要点：战斗是"多回合会话"，与 game.step 的"单动作"模型分离——
  - Battle 持有双方当前 HP/灵气，与 game 共享同一个 rng（随机流一致、可回溯）。
  - 每回合：玩家动作结算 →（敌存活则）敌人行动 → 检查胜负结束。
  - 胜/负/逃的资源结算（掉落、重伤代价、熟悉度成长）由 game 层负责，battle 只裁决战斗本身。

动作集：attack 平砍 / skill <技能> / defend 防御 / flee 遁走 / gather 聚气。
五行克制（P2 只做"克"环；"生"与威力层留 P5）：
  KE = {金克木, 木克土, 土克水, 水克火, 火克金}；
  技能五行 克 目标五行 ×1.5；被目标五行 克 ×0.5；同/无 ×1.0。

P3 utility 最小战斗效果（由技能数据 utility_effect 驱动）：
  breath 吐纳：施放立即回灵（≈3×qi_regen，封顶 qi_max）；
  root   定身：敌方本回合行动跳过；
  weaken 破势：敌方本回合造成伤害 ×0.5；
  evade  御风：敌方本回合攻击 50% 概率落空（消耗随机流）。
效果标记只存在一回合（敌方行动结算后由下一回合重置）。
defense 类技能 = 本回合受创减半（与"防御"动作等效，不差异化）。
"""

# 五行"克"环：键 克 值
KE = {"金": "木", "木": "土", "土": "水", "水": "火", "火": "金"}

# 战斗结局
BATTLE_WIN = "win"
BATTLE_LOSE = "lose"
BATTLE_FLED = "fled"

# 无效指令原因码（P3.5 结构化：game 层读取 Battle.last_reason 映射到 Result.reason）
R_BATTLE_ENDED = "battle_ended"
R_UNKNOWN_ACTION = "unknown_action"
R_UNKNOWN_SKILL = "unknown_skill"
R_SKILL_NA = "skill_na"
R_LOW_QI = "low_qi"

# utility 效果键 → 展示名（CLI/技能列表用）
UTIL_EFFECT_LABELS = {
    "breath": "吐纳", "root": "定身", "weaken": "破势", "evade": "闪避",
}

# 可输入动作的规范化别名（CLI 层再映射到 canonical，engine 层兜底一份）
_ACTION_ALIASES = {
    "attack": "attack", "atk": "attack", "平砍": "attack", "攻": "attack",
    "skill": "skill", "技能": "skill", "术": "skill",
    "defend": "defend", "def": "defend", "防御": "defend", "防": "defend",
    "flee": "flee", "run": "flee", "遁走": "flee", "逃": "flee",
    "gather": "gather", "聚气": "gather", "聚": "gather",
}


def ke_mult(att_el: str, def_el: str) -> float:
    """攻方五行 vs 守方五行 → 伤害系数（同/无 = 1.0）。"""
    if att_el == "无" or def_el == "无" or att_el == def_el:
        return 1.0
    if KE.get(att_el) == def_el:      # 攻克守 ×1.5
        return 1.5
    if KE.get(def_el) == att_el:      # 守克攻 ×0.5
        return 0.5
    return 1.0


def battle_stats(realm_idx: int, qi_max_base: int = 0) -> dict:
    """从 境界档 派生玩家本场临时战斗面板（Player 不存攻防血，派生不入存档）。

    qi_max_base 为灵气池额外上限预留位（功法/器物加成，P3+ 用，当前 0）。
    """
    hp = 60 + realm_idx * 25
    attack = 8 + realm_idx * 4
    defense = 4 + realm_idx * 3
    speed = 8 + realm_idx
    qi_max = 50 + realm_idx * 15 + qi_max_base
    return dict(
        realm_idx=realm_idx,
        hp=hp, hp_max=hp,
        attack=attack, defense=defense, speed=speed,
        qi_max=qi_max, qi=qi_max,
        qi_regen=5 + realm_idx,       # 回合自动回灵 = 5 + 档
    )


def _jitter(rng, salt: str) -> float:
    """伤害浮动系数：0.9 ~ 1.1（±10%），复用传入的随机流。"""
    return 0.9 + rng.roll(salt) * 0.2


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


class Battle:
    """一场战斗的回合状态机。

    构造参数（由 game 层备好）：
      player_stats : battle_stats() 输出的面板 dict（含本场起始满 HP/灵气）
      player_skills: 可用技能对象列表（content.skills.Skill；
                     已按 P3 池规则过滤：free 术法 + 运转池功法已解锁且谱系满足者）
      enemy        : content.enemies.Enemy 实体
      rng          : 复用 Game 的 Rng（保证随机流一致可回溯）
    """

    def __init__(self, player_stats: dict, player_skills: list, enemy, rng):
        ps = player_stats
        self.realm_idx = ps.get("realm_idx", 1)
        # ---- 玩家本场面板（随回合变化的当前值）----
        self.p_hp = ps["hp"]
        self.p_hp_max = ps["hp_max"]
        self.p_qi = ps["qi"]
        self.p_qi_max = ps["qi_max"]
        self.p_qi_regen = ps["qi_regen"]
        self.p_attack = ps["attack"]
        self.p_defense = ps["defense"]
        self.p_speed = ps["speed"]
        # ---- 敌人 ----
        self.enemy = enemy
        self.e_hp = enemy.hp
        # ---- 技能池（按 id 升序稳定排列）----
        self.skills = sorted(player_skills, key=lambda sk: sk.id)
        self._skill_by_id = {sk.id: sk for sk in self.skills}
        # ---- 过程状态 ----
        self._rng = rng
        self.turn = 0
        self.ended = False       # 战斗是否已结束
        self.outcome = None      # win / lose / fled
        self.guard = False       # 本回合玩家处于防御（受创减半）
        # ---- P3：战斗成长与 utility 效果 ----
        self.used = set()        # 本场玩家成功施放的技能 id（结算时按母功法加熟悉度）
        self.enemy_rooted = False    # 敌方本回合被定身（行动跳过）
        self.enemy_weakened = False  # 敌方本回合伤害 ×0.5
        self.self_evading = False    # 敌方本回合攻击 50% 落空
        self.last_reason = ""    # 最近一次 do() 的无效指令原因码（空=指令有效）

    # ---------- 只读视图 / 技能 ----------
    def available_skills(self) -> list:
        """本场可施放的技能（game 层按 P3 池规则备好的全量，含可战 utility）。"""
        return list(self.skills)

    def ke(self, att_el: str) -> float:
        """某技能五行 vs 本场敌人五行的克制系数（bot/决策用）。"""
        return ke_mult(att_el, self.enemy.element)

    def view(self) -> str:
        """当前状态文本：双方 HP / 灵气 / 敌信息。"""
        return (
            f"你：HP {self.p_hp}/{self.p_hp_max}  灵气 {self.p_qi}/{self.p_qi_max}\n"
            f"敌：【{self.enemy.name}】（{self.enemy.element}系·档{self.enemy.realm_idx}）"
            f"  HP {self.e_hp}/{self.enemy.hp}"
        )

    def _hp_line(self) -> str:
        return (f"（你 HP {self.p_hp}/{self.p_hp_max} 灵气 {self.p_qi}/{self.p_qi_max}"
                f" ｜ 敌 HP {self.e_hp}/{self.enemy.hp}）")

    # ---------- 主入口：每回合一步 ----------
    def do(self, action: str, skill_id=None):
        """执行一回合：玩家动作结算 →（敌存活则）敌人行动 → 检查结束。

        返回 (文本, ended, outcome)：ended=False 战斗继续；outcome 仅 ended=True 时有值。
        资源不足/未知动作等"无效指令"不推进回合（玩家可重输），原因码写入 self.last_reason。
        """
        self.last_reason = ""
        if self.ended:
            self.last_reason = R_BATTLE_ENDED
            return "战斗已结束。", True, self.outcome
        act = _ACTION_ALIASES.get((action or "").strip().lower())
        if act is None:
            self.last_reason = R_UNKNOWN_ACTION
            return f"未知战斗动作：{action}（可用：attack/skill/defend/flee/gather）", False, None
        # ---- 无效指令：不推进回合 ----
        if act == "skill":
            sk = self._resolve_skill(skill_id)
            if sk is None:
                self.last_reason = R_UNKNOWN_SKILL
                return f"没有可用技能「{skill_id}」（技能列表见菜单）。", False, None
            if sk.kind == "utility" and not sk.utility_effect:
                self.last_reason = R_SKILL_NA
                return f"【{sk.name}】暂无实战效果，暂无法施展。", False, None
            if self.p_qi < sk.qi_cost:
                self.last_reason = R_LOW_QI
                return (f"灵气不足：【{sk.name}】需 {sk.qi_cost}，当前 {self.p_qi}。"
                        f"（可用 5/聚气 回复）"), False, None
        # ---- 合法动作：回合推进 ----
        self.turn += 1
        lines = []
        # 回合初自动回复灵气
        gain = min(self.p_qi_regen, self.p_qi_max - self.p_qi)
        if gain > 0:
            self.p_qi += gain
            lines.append(f"（灵气自动回复 +{gain}，当前 {self.p_qi}/{self.p_qi_max}）")
        # utility 效果标记只存在一回合：每回合初重置
        self.guard = False
        self.enemy_rooted = False
        self.enemy_weakened = False
        self.self_evading = False

        if act == "attack":
            dmg = max(1, round((self.p_attack - self.enemy.defense * 0.4)
                               * _jitter(self._rng, "bat_atk")))
            self.e_hp -= dmg
            lines.append(f"你欺身强攻【{self.enemy.name}】，造成 {dmg} 点伤害。")
        elif act == "skill":
            self.p_qi -= sk.qi_cost
            self.used.add(sk.id)   # 成功施放（已扣灵气）→ 记入战斗成长
            if sk.kind == "defense":
                self.guard = True
                lines.append(f"你催动【{sk.name}】护体，本回合所受伤害减半。")
            elif sk.kind == "utility":
                self._cast_utility(sk, lines)
            else:  # attack 技能：五行克制生效
                mult = ke_mult(sk.element, self.enemy.element)
                base = sk.power + self.p_attack * 0.5 - self.enemy.defense * 0.3
                dmg = max(1, round(base * mult * _jitter(self._rng, "bat_skill")))
                self.e_hp -= dmg
                tag = ""
                if mult > 1.0:
                    tag = f"（{sk.element}克{self.enemy.element}，威力×{mult:g}）"
                elif mult < 1.0:
                    tag = f"（被{self.enemy.element}所克，威力×{mult:g}）"
                lines.append(f"你施展【{sk.name}】{tag}，造成 {dmg} 点伤害。")
        elif act == "defend":
            self.guard = True
            lines.append("你凝神防御，本回合所受伤害减半。")
        elif act == "gather":
            got = min(3 * self.p_qi_regen, self.p_qi_max - self.p_qi)
            self.p_qi += got
            lines.append(f"你盘膝聚气放弃出手，灵气 +{got}"
                         f"（当前 {self.p_qi}/{self.p_qi_max}）。")
        else:  # flee 遁走
            flee_p = 0.5 + (self.p_speed - self.enemy.speed) * 0.02
            flee_p = _clamp(flee_p, 0.2, 0.9)
            if self._rng.chance(flee_p, "bat_flee"):
                self.ended = True
                self.outcome = BATTLE_FLED
                lines.append(f"你全力遁走，成功脱离战斗！")
                lines.append(self._hp_line())
                return "\n".join(lines), True, BATTLE_FLED
            lines.append(f"遁走失败（成功率约 {flee_p * 100:.0f}%）！"
                         f"【{self.enemy.name}】趁隙扑来——")
        # ---- 敌方行动（遁走成功或敌已毙则跳过）----
        if self.e_hp <= 0:
            self.ended = True
            self.outcome = BATTLE_WIN
            lines.append(f"【{self.enemy.name}】轰然倒地，战斗结束！")
        elif self.p_hp > 0:
            self._enemy_act(lines)
            if self.p_hp <= 0:
                self.ended = True
                self.outcome = BATTLE_LOSE
                lines.append("你伤势过重，眼前一黑，轰然倒下……")
        lines.append(self._hp_line())
        return "\n".join(lines), self.ended, self.outcome

    # ---------- P3：utility 效果与敌方行动 ----
    def _cast_utility(self, sk, lines: list):
        """施放 utility 技能：立即效果（breath）或本回合标记（root/weaken/evade）。"""
        fx = sk.utility_effect
        if fx == "breath":
            got = min(3 * self.p_qi_regen, self.p_qi_max - self.p_qi)
            self.p_qi += got
            lines.append(f"你施展【{sk.name}】吐纳调息，灵气 +{got}"
                         f"（当前 {self.p_qi}/{self.p_qi_max}）。")
        elif fx == "root":
            self.enemy_rooted = True
            lines.append(f"你施展【{sk.name}】缚住【{self.enemy.name}】，其本回合动弹不得！")
        elif fx == "weaken":
            self.enemy_weakened = True
            lines.append(f"你施展【{sk.name}】破其攻势，【{self.enemy.name}】本回合伤害减半！")
        elif fx == "evade":
            self.self_evading = True
            lines.append(f"你施展【{sk.name}】，身形飘忽——本回合敌攻五成落空！")
        # 未知效果键：数据层兜底（不推进任何标记，战斗照常进行）

    def _enemy_act(self, lines: list):
        """敌方本回合行动：按 root/evade/weaken/guard 结算。"""
        if self.enemy_rooted:
            lines.append(f"【{self.enemy.name}】被缚，动弹不得！")
            return
        if self.self_evading and self._rng.chance(0.5, "bat_evade"):
            lines.append(f"【{self.enemy.name}】扑击落空——你身形飘忽，堪堪避开！")
            return
        dmg = max(1, round((self.enemy.attack * 0.6 - self.p_defense * 0.3)
                           * _jitter(self._rng, "bat_edmg")))
        notes = []
        if self.enemy_weakened:
            dmg = max(1, round(dmg * 0.5))
            notes.append("破势削其锋芒")
        if self.guard:
            dmg = max(1, round(dmg * 0.5))
            notes.append("防御卸去大半")
        self.p_hp -= dmg
        if notes:
            lines.append(f"【{self.enemy.name}】扑击而至（{'、'.join(notes)}），你受创 {dmg} 点。")
        else:
            lines.append(f"【{self.enemy.name}】扑击而至，你受创 {dmg} 点。")

    def _resolve_skill(self, skill_id):
        """技能输入（int id）→ 本场技能对象；找不到返回 None。"""
        if skill_id is None:
            return None
        if isinstance(skill_id, int):
            return self._skill_by_id.get(skill_id)
        return None
