import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { createServer } from 'vite';

const vite = await createServer({
  configFile: false, root: fileURLToPath(new URL('..', import.meta.url)),
  server: { middlewareMode: true, hmr: false, watch: null }, appType: 'custom',
});
after(() => vite.close());
const { AppContext } = await vite.ssrLoadModule('/src/shared/state/AppContext.js');
const { default: Home } = await vite.ssrLoadModule('/src/features/home/HomePage.jsx');
const { default: Budget } = await vite.ssrLoadModule('/src/features/budgets/BudgetPage.jsx');
const { default: Status } = await vite.ssrLoadModule('/src/features/preparation/PreparationStatus.jsx');
const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
const forecast = { as_of: new Date().toISOString(), current_balance: 800000, remaining_days: 20, expected_living_cost: 400000, scheduled_expense_total: 150000, available_amount: 250000, shortage_amount: 0 };
const data = { account: { current_balance: 800000, display_name: '생활비 통장' }, settings: { daily_living_budget: 99999, next_income_date: today, expected_income_amount: 0 }, expenses: [], forecast };

function render(Component, status = 'READY') {
  const value = { user: { user_id: 'user1', role: 'OWNER', display_name: '체험 사용자', monitoring_consented_at: forecast.as_of }, data,
    mode: 'api', canTransfer: status === 'READY', preparation: { status, source: 'api', baselineDate: today, forecastDate: today, message: '준비 상태 안내' },
    reload: async () => {}, logout: async () => {}, run: async () => {}, notify: () => {} };
  return renderToStaticMarkup(React.createElement(AppContext.Provider, { value }, React.createElement(MemoryRouter, null, React.createElement(Component))));
}

test('홈 송금은 준비 완료일 때만 링크이고 그 외에는 비활성 버튼', () => {
  assert.match(render(Home), /href="\/transfer"/);
  for (const status of ['CHECKING', 'MISSING', 'STALE', 'ERROR']) {
    const html = render(Home, status);
    assert.doesNotMatch(html, /href="\/transfer"/);
    assert.match(html, /<button[^>]*disabled[^>]*>돈 보내기 · 준비 확인 중/);
  }
});

test('생활비 화면은 프론트 설정으로 재계산하지 않고 서버 결과와 기준 시각을 표시', () => {
  const html = render(Budget);
  assert.match(html, /서버에서 계산한 결과예요/);
  assert.match(html, /250,000원/);
  assert.match(html, /400,000원/);
  assert.match(html, /20일/);
  assert.match(html, /계산 기준/);
});

test('오래됨·실패·확인 중에는 이전 서버 생활비 결과를 현재 금액처럼 보여주지 않음', () => {
  for (const status of ['CHECKING', 'STALE', 'ERROR']) {
    const html = render(Budget, status);
    assert.doesNotMatch(html, /250,000원/);
    assert.match(html, /최신 상태를 확인하지 못했어요/);
  }
});

test('준비 상태에 맞는 안내와 재조회·재로그인 동작 제공', () => {
  assert.match(render(Status), /송금 준비 완료/);
  const checking = render(Status, 'CHECKING');
  assert.match(checking, /송금을 준비하고 있어요/);
  assert.match(checking, /aria-busy="true"/);
  assert.doesNotMatch(checking, /다시 로그인/);
  for (const status of ['MISSING', 'STALE', 'ERROR']) {
    const html = render(Status, status);
    assert.match(html, /다시 조회/);
    assert.match(html, /다시 로그인/);
  }
});
