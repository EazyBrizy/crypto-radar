"use client";

import * as LabelPrimitive from "@radix-ui/react-label";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  FormProvider,
  useForm,
  useFormContext,
  type FieldValues,
  type Path,
  type Resolver,
  type SubmitHandler,
  type UseFormReturn,
  type UseFormProps
} from "react-hook-form";

import { Input, type InputProps } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export function useZodForm<TFieldValues extends FieldValues>(
  schema: Parameters<typeof zodResolver>[0],
  options?: UseFormProps<TFieldValues>
) {
  return useForm<TFieldValues>({
    resolver: zodResolver(schema) as Resolver<TFieldValues>,
    ...options
  });
}

interface ValidatedFormProps<TFieldValues extends FieldValues> {
  form: UseFormReturn<TFieldValues>;
  onSubmit: SubmitHandler<TFieldValues>;
  className?: string;
  children: React.ReactNode;
}

export function ValidatedForm<TFieldValues extends FieldValues>({
  form,
  onSubmit,
  className,
  children
}: ValidatedFormProps<TFieldValues>) {
  return (
    <FormProvider {...form}>
      <form className={cn("form-grid", className)} onSubmit={form.handleSubmit(onSubmit)}>
        {children}
      </form>
    </FormProvider>
  );
}

interface FormTextFieldProps<TFieldValues extends FieldValues>
  extends Omit<InputProps, "name"> {
  name: Path<TFieldValues>;
  label: string;
  description?: string;
}

export function FormTextField<TFieldValues extends FieldValues>({
  name,
  label,
  description,
  className,
  ...props
}: FormTextFieldProps<TFieldValues>) {
  const {
    register,
    formState: { errors }
  } = useFormContext<TFieldValues>();
  const error = errors[name]?.message;

  return (
    <div className="form-field">
      <LabelPrimitive.Root className="form-label" htmlFor={name}>
        {label}
      </LabelPrimitive.Root>
      <Input id={name} className={className} aria-invalid={Boolean(error)} {...register(name)} {...props} />
      {description ? <p className="form-description">{description}</p> : null}
      {typeof error === "string" ? <p className="form-error">{error}</p> : null}
    </div>
  );
}
