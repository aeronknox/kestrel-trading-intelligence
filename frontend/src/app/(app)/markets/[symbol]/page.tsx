import type { Metadata } from "next";

import { AssetDetailView } from "@/features/markets/asset-detail-view";

export async function generateMetadata({ params }: { params: Promise<{ symbol: string }> }): Promise<Metadata> {
  const { symbol } = await params;
  return { title: decodeURIComponent(symbol).toUpperCase() };
}

export default async function AssetPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  return <AssetDetailView symbol={decodeURIComponent(symbol).toUpperCase()} />;
}
