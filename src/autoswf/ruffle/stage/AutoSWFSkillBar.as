package {
    import flash.display.Sprite;
    import flash.events.MouseEvent;
    import flash.text.TextField;

    /** The AQW-like action bar: Auto (Attack1 and Attack2 in turn, like AQW's auto attack) and skills 1-5 (the slots of
     *  the settings: a game label and the armor animation it plays). Hovering a slot shows its game label. */
    public class AutoSWFSkillBar extends Sprite {
        public static const SLOT:int = 46;
        private var tip:TextField;

        public function AutoSWFSkillBar(stageRef:AutoSWFStage, slots:Array) {
            super();
            var x:Number = 7;
            add(stageRef, "A", "Auto", "Auto attack: Attack1 / Attack2", x, function ():void { stageRef.autoAttack(); });
            for each (var slot:Object in slots) {
                x += SLOT + 4;
                var game:String = slot.game;
                var name:String = slot.armor != null ? slot.armor : game;
                add(stageRef, String(slot.slot), name, game + (slot.armor != null ? "  →  " + slot.armor : ""), x,
                    skillOf(stageRef, game));
            }
            graphics.lineStyle(2, AutoSWFButton.GOLD);
            graphics.beginFill(AutoSWFButton.BROWN, 0.96);
            graphics.drawRoundRect(0, 0, x + SLOT + 7, SLOT + 12, 10, 10);
            graphics.endFill();
            tip = AutoSWFButton.text("", 11, 0xFFFFFF);
            tip.background = true;
            tip.backgroundColor = 0x000000;
            tip.visible = false;
            tip.y = -22;
            addChild(tip);
        }

        private function skillOf(stageRef:AutoSWFStage, game:String):Function {
            return function ():void { stageRef.useSkill(game); };
        }

        private function add(stageRef:AutoSWFStage, key:String, name:String, hint:String, x:Number,
                             onClick:Function):void {
            var slot:Sprite = new Sprite();
            slot.x = x;
            slot.y = 6;
            slot.graphics.lineStyle(1, AutoSWFButton.GOLD);
            slot.graphics.beginFill(AutoSWFButton.DARK);
            slot.graphics.drawRoundRect(0, 0, SLOT, SLOT, 8, 8);
            slot.graphics.endFill();
            var k:TextField = AutoSWFButton.text(key, 14, AutoSWFButton.CREAM, true);
            k.x = Math.round((SLOT - k.width) / 2);
            k.y = 4;
            slot.addChild(k);
            var n:TextField = AutoSWFButton.text(name.length > 8 ? name.substr(0, 7) + "…" : name, 9, AutoSWFButton.CREAM);
            n.x = Math.round((SLOT - n.width) / 2);
            n.y = 26;
            slot.addChild(n);
            slot.buttonMode = true;
            slot.mouseChildren = false;
            slot.addEventListener(MouseEvent.CLICK, function (e:MouseEvent):void { onClick(); });
            slot.addEventListener(MouseEvent.MOUSE_OVER, function (e:MouseEvent):void {
                tip.text = hint;
                tip.x = x;
                tip.visible = true;
            });
            slot.addEventListener(MouseEvent.MOUSE_OUT, function (e:MouseEvent):void { tip.visible = false; });
            addChild(slot);
        }
    }
}
