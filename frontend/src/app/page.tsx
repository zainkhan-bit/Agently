import { brand } from "@/config/brand";
import { HomeNav } from "@/features/auth/HomeNav";
import { ServiceStatus } from "@/features/system/ServiceStatus";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-8 px-4 py-16">
      <header>
        <h1 className="text-4xl font-bold tracking-tight">{brand.name}</h1>
        <p className="mt-2 text-xl">{brand.tagline}</p>
        <p className="mt-4 text-base opacity-80">{brand.description}</p>
      </header>
      <HomeNav />
      <ServiceStatus />
    </main>
  );
}
