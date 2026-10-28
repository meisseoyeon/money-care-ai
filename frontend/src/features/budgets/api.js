export function createBudgetApi(request) {
  return {
    saveBudget: (payload) => request('/budget-settings', { method: 'PUT', body: payload }),
    saveExpense: (payload) => request(payload.id ? `/scheduled-expenses/${payload.id}` : '/scheduled-expenses', { method: payload.id ? 'PATCH' : 'POST', body: payload }),
  };
}
