import { seoulDate } from './state.js';

const messages = {
  MISSING: '송금에 필요한 통계와 생활비 결과가 아직 없어요. 다시 로그인하면 준비할 수 있어요.',
  STALE: '잔액이나 생활비 계획이 바뀌었어요. 다시 로그인해 최신 결과를 준비해 주세요.',
  ERROR: '준비 상태를 확인하지 못했어요. 연결을 확인하고 다시 조회해 주세요.',
};

export function createPreparationApi(request) {
  return {
    async loadPreparation() {
      const results = await Promise.allSettled([request('/baselines/current'), request('/budget-forecasts/latest')]);
      const failures = results.filter((result) => result.status === 'rejected').map((result) => result.reason);
      const unauthorized = failures.find((error) => error.status === 401);
      if (unauthorized) throw unauthorized;
      const baseline = results[0].status === 'fulfilled' ? results[0].value : null;
      const forecast = results[1].status === 'fulfilled' ? results[1].value : null;
      if (failures.length) {
        const status = failures.some((error) => ![404, 409].includes(error.status)) ? 'ERROR'
          : failures.some((error) => error.status === 409) ? 'STALE' : 'MISSING';
        return { baseline, forecast, preparation: { status, source: 'api', message: messages[status] } };
      }
      const valid = baseline && forecast && baseline.user_id === forecast.user_id
        && Number.isInteger(baseline.out_count_30d) && baseline.out_count_30d >= 0
        && baseline.calculation_version && forecast.calculation_version
        && Number.isFinite(Date.parse(baseline.as_of)) && Number.isFinite(Date.parse(forecast.as_of))
        && Number.isInteger(forecast.remaining_days) && forecast.remaining_days >= 0
        && ['current_balance', 'scheduled_expense_total', 'daily_living_budget', 'expected_living_cost', 'available_amount', 'shortage_amount'].every((key) => Number.isSafeInteger(forecast[key]));
      if (!valid) return { baseline: null, forecast: null, preparation: { status: 'ERROR', source: 'api', message: '준비 결과의 형식을 확인하지 못했어요. 다시 조회해 주세요.' } };
      return { baseline, forecast, preparation: { status: 'READY', source: 'api', message: '송금 준비가 끝났어요.', baselineDate: baseline.base_date, forecastDate: seoulDate(forecast.as_of) } };
    },
  };
}
