// 申请状态展示配置
export const STATUS_MAP = {
  check: { label: '待材料检查', cls: 'check' },
  supplement: { label: '待补件', cls: 'supplement' },
  manual: { label: '待人工核验', cls: 'manual' },
  risk: { label: '待风控复核', cls: 'risk' },
  approved: { label: '已审批', cls: 'ok' },
  rejected: { label: '已拒绝', cls: 'danger' }
}

// 产品选项（业务配置）
export const PRODUCTS = ['普惠小微经营贷', '经营性抵押贷', '科技e贷', '小微快贷']

// 材料清单固定分类（顺序即展示顺序）
export const MATERIAL_CATEGORIES = [
  { key: 'business_license', label: '营业执照', icon: '🪪' },
  { key: 'bank_statement', label: '银行流水', icon: '🏦' },
  { key: 'financial_report', label: '财务报表', icon: '📊' },
  { key: 'tax_return', label: '纳税申请表', icon: '🧾' },
  { key: 'credit_auth', label: '征信授权书', icon: '📝' },
  { key: 'other', label: '其他', icon: '📁' }
]
