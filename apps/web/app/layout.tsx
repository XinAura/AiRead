import type { Metadata } from "next";
import { BookOpenText, Library } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Providers } from "@/lib/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "AiRead 工作台",
  description: "个人资料解析与有声化工作台",
};

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <Providers>
          <div className="app-shell">
            <aside className="sidebar">
              <Link className="brand" href="/library">
                <span className="brand-mark">
                  <BookOpenText size={19} />
                </span>
                <span>AiRead</span>
              </Link>
              <nav aria-label="主导航">
                <Link className="nav-item active" href="/library">
                  <Library size={17} />
                  资料库
                </Link>
              </nav>
              <div className="sidebar-note">
                <span className="status-dot" />
                本地工作区
              </div>
            </aside>
            <main className="main-content">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
