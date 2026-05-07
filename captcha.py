#!/usr/bin/env python3
"""
图形验证码模块
作者: 云舟
功能: 生成和验证图形验证码，防止暴力破解

策略:
    - 使用 Pillow 库生成验证码图片
    - 验证码长度：4 位（字母+数字）
    - 验证码有效期：5 分钟
    - 内存缓存验证码数据
"""

import random
import string
import uuid
import hashlib
import io
import base64
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

# 尝试导入 Pillow（如果未安装，使用简化版本）
try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    print("[验证码] Pillow 未安装，使用简化版本")


# ========== 配置 ==========

# 验证码参数
CAPTCHA_LENGTH = 4  # 验证码长度
CAPTCHA_EXPIRE_MINUTES = 5  # 验证码有效期（分钟）
CAPTCHA_CHARS = string.ascii_uppercase + string.digits  # 可用字符（排除易混淆字符）

# 内存缓存：存储验证码数据
# 格式: {captcha_id: {'code': '验证码', 'expires': 过期时间}}
captcha_store: Dict[str, Dict] = {}


# ========== 验证码生成 ==========

def generate_captcha_code(length: int = CAPTCHA_LENGTH) -> str:
    """
    生成随机验证码文本
    
    Args:
        length: 验证码长度
        
    Returns:
        验证码字符串
    """
    # 排除易混淆的字符（I、O、0、1）
    chars = CAPTCHA_CHARS.replace('I', '').replace('O', '').replace('0', '').replace('1', '')
    
    return ''.join(random.choices(chars, k=length))


def generate_captcha_id() -> str:
    """
    生成唯一的验证码 ID
    
    Returns:
        验证码 ID（UUID）
    """
    return str(uuid.uuid4())


def create_captcha_image_simple(code: str) -> str:
    """
    创建简化版验证码（纯文本，用于无 Pillow 环境）
    
    Args:
        code: 验证码文本
        
    Returns:
        Base64 编码的图片数据（SVG 格式）
    """
    # 使用 SVG 创建简单的验证码
    svg_template = f'''<svg xmlns="http://www.w3.org/2000/svg" width="120" height="50">
        <rect width="100%" height="100%" fill="#1a1a2e"/>
        <text x="60" y="30" font-family="monospace" font-size="24" 
              fill="#00d9ff" text-anchor="middle">{code}</text>
    </svg>'''
    
    # 返回 Base64 编码
    return base64.b64encode(svg_template.encode('utf-8')).decode('utf-8')


def create_captcha_image_pillow(code: str) -> str:
    """
    使用 Pillow 创建验证码图片
    
    Args:
        code: 验证码文本
        
    Returns:
        Base64 编码的 PNG 图片数据
    """
    # 图片尺寸
    width, height = 120, 50
    
    # 创建图片（深色背景）
    image = Image.new('RGB', (width, height), color=(26, 26, 46))
    
    # 创建绘图对象
    draw = ImageDraw.Draw(image)
    
    # 尝试加载字体（如果失败，使用默认字体）
    try:
        # 使用系统字体
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 48)
    except:
        # 使用默认字体
        font = ImageFont.load_default()
    
    # 计算文本位置（居中）
    text_width = len(code) * 28  # 粗略估计
    text_height = 48
    x = (width - text_width) // 2
    y = (height - text_height) // 2
    
    # 绘制验证码文本（带干扰效果）
    for i, char in enumerate(code):
        # 随机颜色（青色系）
        color = (random.randint(0, 100), random.randint(200, 255), random.randint(200, 255))
        
        # 随机位置偏移
        char_x = x + i * 28 + random.randint(-3, 3)
        char_y = y + random.randint(-3, 3)
        
        # 绘制字符
        draw.text((char_x, char_y), char, font=font, fill=color)
    
    # 添加干扰线
    for _ in range(1):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        
        # 随机颜色（浅色）
        color = (random.randint(50, 150), random.randint(50, 150), random.randint(50, 150))
        
        draw.line([(x1, y1), (x2, y2)], fill=color, width=1)
    
    # 添加噪点
    for _ in range(15):
        x = random.randint(0, width)
        y = random.randint(0, height)
        
        color = (random.randint(50, 200), random.randint(50, 200), random.randint(50, 200))
        
        draw.point((x, y), fill=color)
    
    # 应用滤镜（扭曲效果）
    # image = image.filter(ImageFilter.SMOOTH)
    
    # 转换为 Base64
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    return img_base64


def generate_captcha() -> Tuple[str, str]:
    """
    生成完整的验证码（包含 ID 和图片）
    
    Returns:
        (captcha_id, captcha_image_base64)
    """
    # 生成验证码文本
    code = generate_captcha_code()
    
    # 生成验证码 ID
    captcha_id = generate_captcha_id()
    
    # 存储验证码数据
    expires = datetime.now() + timedelta(minutes=CAPTCHA_EXPIRE_MINUTES)
    captcha_store[captcha_id] = {
        'code': code,
        'expires': expires,
        'created': datetime.now()
    }
    
    # 生成验证码图片
    if HAS_PILLOW:
        img_base64 = create_captcha_image_pillow(code)
    else:
        img_base64 = create_captcha_image_simple(code)
    
    return captcha_id, img_base64


# ========== 验证码验证 ==========

def verify_captcha(captcha_id: str, user_input: str) -> Tuple[bool, str]:
    """
    验证用户输入的验证码
    
    Args:
        captcha_id: 验证码 ID
        user_input: 用户输入的验证码
        
    Returns:
        (验证是否成功, 错误消息)
    """
    # 检查验证码是否存在
    if captcha_id not in captcha_store:
        return False, '验证码不存在或已过期'
    
    # 检查验证码是否过期
    captcha_data = captcha_store[captcha_id]
    
    if captcha_data['expires'] < datetime.now():
        # 清理过期验证码
        del captcha_store[captcha_id]
        return False, '验证码已过期，请重新获取'
    
    # 验证输入（忽略大小写）
    correct_code = captcha_data['code'].upper()
    user_code = user_input.strip().upper()
    
    if user_code != correct_code:
        return False, '验证码错误'
    
    # 验证成功，删除验证码（防止重复使用）
    del captcha_store[captcha_id]
    
    return True, '验证码验证成功'


# ========== 辅助函数 ==========

def cleanup_expired_captchas():
    """
    清理过期的验证码
    """
    now = datetime.now()
    
    expired_ids = [
        id for id, data in captcha_store.items()
        if data['expires'] < now
    ]
    
    for id in expired_ids:
        del captcha_store[id]
    
    if expired_ids:
        print(f"[验证码] 已清理 {len(expired_ids)} 个过期验证码")


def get_captcha_stats() -> Dict:
    """
    获取验证码统计信息
    
    Returns:
        统计信息 dict
    """
    cleanup_expired_captchas()
    
    return {
        'active_count': len(captcha_store),
        'expire_minutes': CAPTCHA_EXPIRE_MINUTES
    }


# ========== Flask API 辅助 ==========

def get_captcha_response() -> Dict:
    """
    生成验证码 API 响应
    
    Returns:
        API 响应 dict
    """
    captcha_id, img_base64 = generate_captcha()
    
    return {
        'success': True,
        'captcha_id': captcha_id,
        'captcha_image': f'data:image/png;base64,{img_base64}',
        'expires_in': CAPTCHA_EXPIRE_MINUTES * 60  # 秒
    }


if __name__ == '__main__':
    # 测试验证码生成
    print("测试验证码生成...")
    
    # 生成验证码
    captcha_id, img_base64 = generate_captcha()
    
    print(f"  验证码 ID: {captcha_id}")
    print(f"  验证码图片（Base64前50字符）: {img_base64[:50]}...")
    
    # 测试验证
    captcha_data = captcha_store[captcha_id]
    print(f"  正确验证码: {captcha_data['code']}")
    
    # 测试正确输入
    success, msg = verify_captcha(captcha_id, captcha_data['code'])
    print(f"  正确输入验证: {success} - {msg}")
    
    # 测试错误输入（重新生成验证码）
    captcha_id2, img_base64_2 = generate_captcha()
    success2, msg2 = verify_captcha(captcha_id2, 'WRONG')
    print(f"  错误输入验证: {success2} - {msg2}")
    
    # 查看统计
    stats = get_captcha_stats()
    print(f"\n统计信息: {stats}")