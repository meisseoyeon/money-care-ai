// 자동 조회는 화면을 유지하고, 같은 시점의 중복 요청은 하나로 합칩니다.
export function createReloadController({ load, onChecking, onSuccess, onError, canBackground = () => true }) {
  let revision = 0;
  let inFlight = null;

  return {
    // 로그인 변경/송금 시작 전에 이전 조회 결과의 반영을 막습니다.
    invalidate() { revision += 1; },

    reload({ background = false } = {}) {
      if (background && !canBackground()) return Promise.resolve(null);
      if (inFlight?.revision === revision) return inFlight.promise;
      const current = ++revision;
      if (!background) onChecking();
      const promise = Promise.resolve().then(load).then((next) => {
        if (current === revision) onSuccess(next);
        return next;
      }).catch((error) => {
        if (current === revision) onError(error);
        throw error;
      }).finally(() => {
        if (inFlight?.revision === current) inFlight = null;
      });
      inFlight = { revision: current, promise };
      return promise;
    },
  };
}
