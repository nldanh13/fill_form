import type { Metadata } from "next";
import "./globals.css";
export const metadata:Metadata={title:"Trợ lý điền phiếu hàng tháng",description:"Quản lý và tự động hóa biểu mẫu đánh giá kỹ thuật điều dưỡng",other:{"codex-preview":"development"},icons:{icon:"/favicon.svg",shortcut:"/favicon.svg"}};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="vi"><body className="antialiased">{children}</body></html>}
