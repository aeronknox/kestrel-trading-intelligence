"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, MailWarning, XCircle } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/primitives";
import { ME_KEY } from "@/hooks/use-auth";
import { api } from "@/services/api";

/** Read the one-time token from the URL once, then drop it from the address bar and history. */
function useUrlToken(): string | null {
  const params = useSearchParams();
  const [token] = useState(() => params.get("token"));
  useEffect(() => {
    if (token) window.history.replaceState(null, "", window.location.pathname);
  }, [token]);
  return token;
}

function Heading({ title, body }: { title: string; body: React.ReactNode }) {
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{body}</p>
    </>
  );
}

function ErrorNote({ message }: { message: string }) {
  return <p className="rounded-md bg-loss-soft px-3 py-2 text-xs text-loss" role="alert">{message}</p>;
}

// ------------------------------------------------------------ forgot password
export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const send = useMutation({ mutationFn: () => api.auth.forgotPassword(email) });
  if (send.isSuccess) {
    return (
      <div>
        <Heading title="Check your email" body={send.data.message} />
        <p className="mt-6 text-sm text-muted-foreground">
          The link expires soon and works once. Didn&apos;t get it? Check spam, or{" "}
          <button type="button" className="font-medium text-primary hover:underline" onClick={() => send.reset()}>try again</button>.
        </p>
        <Button asChild variant="outline" className="mt-6 w-full"><Link href="/login">Back to sign in</Link></Button>
      </div>
    );
  }
  return (
    <div>
      <Heading title="Reset your password" body="Enter your account email and we'll send you a link to choose a new password." />
      <form className="mt-8 grid gap-4" noValidate onSubmit={(e) => { e.preventDefault(); send.mutate(); }}>
        <Field label="Email" htmlFor="email">
          <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        {send.error && <ErrorNote message={send.error.message} />}
        <Button type="submit" loading={send.isPending} disabled={!/^\S+@\S+\.\S+$/.test(email)}>Send reset link</Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted-foreground">
        Remembered it? <Link href="/login" className="font-medium text-primary hover:underline">Sign in</Link>
      </p>
    </div>
  );
}

// ------------------------------------------------------------- reset password
export function ResetPasswordForm() {
  const token = useUrlToken();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const reset = useMutation({ mutationFn: () => api.auth.resetPassword(token!, password) });
  const weak = password && (password.length < 10 || !/[a-z]/i.test(password) || !/\d/.test(password));
  const mismatch = confirm && confirm !== password;

  if (!token) {
    return (
      <div>
        <Heading title="Link missing" body="Open the link from your reset email, or request a new one." />
        <Button asChild className="mt-6 w-full"><Link href="/forgot-password">Request a new link</Link></Button>
      </div>
    );
  }
  if (reset.isSuccess) {
    return (
      <div>
        <Heading title="Password updated" body="You've been signed out on all devices. Sign in with your new password." />
        <Button asChild className="mt-6 w-full"><Link href="/login">Sign in</Link></Button>
      </div>
    );
  }
  return (
    <div>
      <Heading title="Choose a new password" body="Resetting signs you out everywhere you're signed in." />
      <form className="mt-8 grid gap-4" noValidate onSubmit={(e) => { e.preventDefault(); reset.mutate(); }}>
        <Field label="New password" htmlFor="password" hint="At least 10 characters, with letters and numbers." error={weak ? "At least 10 characters, with letters and numbers." : null}>
          <Input id="password" type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label="Confirm password" htmlFor="confirm" error={mismatch ? "Passwords don't match" : null}>
          <Input id="confirm" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </Field>
        {reset.error && <ErrorNote message={reset.error.message} />}
        <Button type="submit" loading={reset.isPending} disabled={!password || !!weak || confirm !== password}>Update password</Button>
      </form>
      {reset.error && (
        <p className="mt-4 text-center text-sm"><Link href="/forgot-password" className="font-medium text-primary hover:underline">Request a new link</Link></p>
      )}
    </div>
  );
}

// --------------------------------------------------------------- verify email
export function VerifyEmailView() {
  const token = useUrlToken();
  const qc = useQueryClient();
  const verify = useMutation({
    mutationFn: () => api.auth.verifyEmail(token!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ME_KEY }),
  });
  const started = useRef(false);
  useEffect(() => {
    // Submit once on load; the ref guards against React's development double-invocation.
    if (token && !started.current) {
      started.current = true;
      verify.mutate();
    }
  }, [token, verify]);

  const signedIn = Boolean(qc.getQueryData(ME_KEY));
  if (!token || verify.isError) {
    return (
      <div>
        <XCircle className="mb-4 size-8 text-loss" />
        <Heading title="We couldn't verify your email" body={verify.error?.message ?? "Open the link from your verification email."} />
        <p className="mt-4 text-sm text-muted-foreground">Sign in and use “Resend email” on the banner to get a fresh link.</p>
        <Button asChild className="mt-6 w-full"><Link href={signedIn ? "/dashboard" : "/login"}>{signedIn ? "Go to dashboard" : "Sign in"}</Link></Button>
      </div>
    );
  }
  if (verify.isSuccess) {
    return (
      <div>
        <CheckCircle2 className="mb-4 size-8 text-gain" />
        <Heading title="Email verified" body="Thanks for confirming your address." />
        <Button asChild className="mt-6 w-full"><Link href={signedIn ? "/dashboard" : "/login"}>{signedIn ? "Go to dashboard" : "Sign in"}</Link></Button>
      </div>
    );
  }
  return <Heading title="Verifying…" body="Confirming your email address." />;
}

// ---------------------------------------------------------- in-app reminder
export function VerifyEmailBanner({ email }: { email: string }) {
  const resend = useMutation({
    mutationFn: api.auth.resendVerification,
    onSuccess: (r) => toast.success(r.message),
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-warn/40 bg-warn-soft px-4 py-2.5 text-sm" role="status">
      <MailWarning className="size-4 shrink-0 text-warn" />
      <p className="min-w-0 flex-1">
        Confirm your email address <span className="font-medium">{email}</span> so you can reset your password if you forget it.
      </p>
      <Button size="sm" variant="outline" loading={resend.isPending} disabled={resend.isSuccess} onClick={() => resend.mutate()}>
        {resend.isSuccess ? "Email sent" : "Resend email"}
      </Button>
    </div>
  );
}
