export const CHECKING = { status: 'CHECKING', message: '송금과 생활비 준비 상태를 확인하고 있어요.' };

export function seoulDate(value = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(value));
  return ['year', 'month', 'day'].map((key) => parts.find((part) => part.type === key).value).join('-');
}

export function effectivePreparation(preparation, now = new Date()) {
  if (preparation?.status !== 'READY' || preparation.source === 'mock') return preparation ?? CHECKING;
  if (preparation.baselineDate !== seoulDate(now) || preparation.forecastDate !== seoulDate(now)) {
    return { ...preparation, status: 'STALE', message: '날짜가 바뀌었어요. 다시 로그인해 오늘의 생활비를 준비해 주세요.' };
  }
  return preparation;
}

export function isPreparationReady(preparation, now = new Date()) {
  return effectivePreparation(preparation, now).status === 'READY';
}

export function visibleForecast(data, preparation, now = new Date()) {
  const status = effectivePreparation(preparation, now).status;
  if (['CHECKING', 'STALE', 'ERROR'].includes(status)) return null;
  return data.forecast ?? null;
}
