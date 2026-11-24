import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef } from "react";

/** The router, except that a late answer cannot navigate once its page has been left. */
export function usePageRouter() {
  const router = useRouter();
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  return useMemo(
    () => ({
      replace: (href: string) => {
        if (mounted.current) router.replace(href);
      },
      push: (href: string) => {
        if (mounted.current) router.push(href);
      },
    }),
    [router],
  );
}
