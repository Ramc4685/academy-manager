"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  SharedShellSkeleton,
  sharedShellClassName,
} from "@/components/shared/shell-skeleton";
import { onAuthChange } from "@/lib/auth/firebase";

export default function SharedLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  const [signedIn, setSignedIn] = useState(false);

  useEffect(
    () =>
      onAuthChange((user) => {
        setSignedIn(Boolean(user));
        setChecked(true);
        if (!user) router.replace("/login");
      }),
    [router]
  );

  // Auth unresolved, or signed out and mid-redirect to /login: hold the shell
  // with a neutral skeleton rather than flashing bare status text.
  if (!checked || !signedIn) {
    return (
      <SharedShellSkeleton
        className={sharedShellClassName}
        testId="shared-auth-skeleton"
      />
    );
  }

  return <main className={sharedShellClassName}>{children}</main>;
}
