/** craft.js computePlan 单元测试：配方树展开 / 熔炼产物兜底 / 无配方兜底
 * 运行：node tools/test_craft_plan.js（依赖 .minecraft/assistant 的 npm 安装） */
'use strict';
const recipes = require('../.minecraft/assistant/recipes');
const { computePlan } = require('../.minecraft/assistant/craft');

let failed = 0;
function check(name, cond, extra = '') {
  console.log(`${cond ? 'PASS' : 'FAIL'} ${name}${extra ? ' | ' + extra : ''}`);
  if (!cond) failed += 1;
}

const index = recipes.buildIndex({ mcVersion: '1.20.1', modsDirs: [] });

// 1) 钻石剑：中间物展开 + 成品排最后 + 材料聚合
const p1 = computePlan(index, 'diamond_sword', 1);
const stepNames = p1.steps.map((s) => s.name);
console.log('  steps:', stepNames.join(' → '), '| needs:', JSON.stringify([...p1.needs.entries()]));
check('计划含 stick 与 diamond_sword 两个合成步骤',
  stepNames.includes('stick') && stepNames.includes('diamond_sword'));
check('成品排在步骤最后', stepNames[stepNames.length - 1] === 'diamond_sword');
check('基础材料含 2 钻石', (p1.needs.get('diamond') || 0) >= 2, String(p1.needs.get('diamond')));
check('原木只需 1 根（聚合展开正确）', (p1.needs.get('oak_log') || 0) === 1,
  String(p1.needs.get('oak_log')));
check('无熔炼拦截项', p1.blocked.length === 0);

// 2) 批量：3 把剑 → 钻石需求 6
const p2 = computePlan(index, 'diamond_sword', 3);
check('3 把剑 → 钻石 6', (p2.needs.get('diamond') || 0) === 6, String(p2.needs.get('diamond')));

// 3) 熔炼产物（铁锭）当基础材料，不走「铁块→9铁锭」反向合成
const p3 = computePlan(index, 'iron_ingot', 1);
check('铁锭当基础材料（不走反向合成）',
  (p3.needs.get('iron_ingot') || 0) === 1 && !p3.steps.some((s) => s.name === 'iron_block'));

// 4) 无任何配方的基础物品直接进 needs
const p4 = computePlan(index, 'dirt', 1);
check('dirt 直接作为基础材料',
  (p4.needs.get('dirt') || 0) === 1, JSON.stringify([...p4.needs.entries()]));

process.exit(failed ? 1 : 0);
